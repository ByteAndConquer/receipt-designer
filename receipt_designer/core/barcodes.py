from __future__ import annotations

"""
Barcode rendering helpers.

Dependencies (all optional, but recommended):
- Pillow                  → pip install pillow
- python-barcode          → pip install python-barcode[images]
- qrcode (for QR Code)    → pip install qrcode[pil]
- treepoem (PDF417, DM, Aztec, GS1, UPC-E, Codabar, etc.)
    → pip install treepoem
    (requires Ghostscript installed & on PATH)
"""

from typing import Optional, Dict, Tuple


from PySide6 import QtGui, QtCore

# Cache for rendered barcode images:
# key = (normalized_kind, data_string)
_BARCODE_QIMAGE_CACHE: Dict[Tuple[str, str], QtGui.QImage] = {}

# --- Optional deps ---------------------------------------------------------

try:
    from PIL import Image  # type: ignore[import]
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

try:
    import barcode  # type: ignore[import]
    from barcode.writer import ImageWriter  # type: ignore[import]
except Exception:  # pragma: no cover
    barcode = None  # type: ignore[assignment]
    ImageWriter = object  # type: ignore[assignment]

try:
    import qrcode  # type: ignore[import]
except Exception:  # pragma: no cover
    qrcode = None  # type: ignore[assignment]

try:
    import treepoem  # type: ignore[import]
except Exception:  # pragma: no cover
    treepoem = None  # type: ignore[assignment]


# --- Exceptions & checksums -----------------------------------------------


class BarcodeValidationError(Exception):
    """Raised when barcode data is invalid for the selected symbology."""
    pass


def ean13_checksum(data: str) -> str:
    """
    Compute the EAN-13 checksum digit for the first 12 digits of `data`.
    """
    digits = [int(ch) for ch in data[:12] if ch.isdigit()]
    if len(digits) != 12:
        raise ValueError("EAN-13 requires at least 12 digits for checksum")

    s = 0
    for i, d in enumerate(digits):
        s += d * (3 if (i % 2 == 1) else 1)
    return str((10 - (s % 10)) % 10)


def upca_checksum(data: str) -> str:
    """
    Compute the UPC-A checksum digit for the first 11 digits of `data`.
    """
    digits = [int(ch) for ch in data[:11] if ch.isdigit()]
    if len(digits) != 11:
        raise ValueError("UPC-A requires at least 11 digits for checksum")

    odd_sum = sum(digits[0::2])
    even_sum = sum(digits[1::2])
    total = odd_sum * 3 + even_sum
    return str((10 - (total % 10)) % 10)

def ean8_checksum(data: str) -> str:
    """
    Compute the EAN-8 checksum digit for the first 7 digits of `data`.
    """
    digits = [int(ch) for ch in data[:7] if ch.isdigit()]
    if len(digits) != 7:
        raise ValueError("EAN-8 requires at least 7 digits for checksum")
    
    # EAN-8 uses alternating weights: 3, 1, 3, 1, 3, 1, 3
    s = 0
    for i, d in enumerate(digits):
        s += d * (3 if (i % 2 == 0) else 1)
    return str((10 - (s % 10)) % 10)


def isbn10_checksum(data: str) -> str:
    """
    Compute ISBN-10 checksum for first 9 characters.
    Returns '0'-'9' or 'X' for check digit.
    """
    data = data[:9]
    if len(data) != 9 or not data.isdigit():
        raise ValueError("ISBN-10 checksum requires 9 digits")
    
    total = sum((10 - i) * int(data[i]) for i in range(9))
    check = (11 - (total % 11)) % 11
    return 'X' if check == 10 else str(check)


def issn_checksum(data: str) -> str:
    """
    Compute ISSN checksum for first 7 digits.
    Returns '0'-'9' or 'X' for check digit.
    """
    data = data[:7]
    if len(data) != 7 or not data.isdigit():
        raise ValueError("ISSN checksum requires 7 digits")
    
    total = sum((8 - i) * int(data[i]) for i in range(7))
    check = (11 - (total % 11)) % 11
    return 'X' if check == 10 else str(check)


def isbn10_to_isbn13(isbn10: str) -> str:
    """
    Convert ISBN-10 to ISBN-13.
    
    Args:
        isbn10: 10-character ISBN-10 (with or without hyphens)
    
    Returns:
        13-digit ISBN-13 string
    
    Example:
        isbn10_to_isbn13("0596520689") -> "9780596520687"
        isbn10_to_isbn13("0-596-52068-9") -> "9780596520687"
    """
    isbn10 = isbn10.strip().upper().replace('-', '').replace(' ', '')
    if len(isbn10) != 10:
        raise ValueError(f"Invalid ISBN-10 length: {len(isbn10)} (expected 10)")
    
    # Add 978 prefix and recalculate checksum using EAN-13 algorithm
    isbn13_base = '978' + isbn10[:9]
    checksum = ean13_checksum(isbn13_base)
    return isbn13_base + checksum

# --- Utility: Pillow → QImage ---------------------------------------------


def _pil_to_qimage(img) -> QtGui.QImage:
    """
    Convert a Pillow Image to a QtGui.QImage.
    """
    if Image is None:
        raise RuntimeError("Pillow is not available")

    img = img.convert("RGBA")
    w, h = img.size
    data = img.tobytes("raw", "RGBA")
    qimg = QtGui.QImage(data, w, h, QtGui.QImage.Format.Format_RGBA8888)
    return qimg.copy()  # detach from original buffer


# --- 1D (python-barcode) --------------------------------------------------


def _render_1d_barcode(kind: str, data: str) -> Optional[QtGui.QImage]:
    """
    Render simple 1D symbologies using python-barcode, if available.

    Covers:
      - Code 128
      - Code 39
      - EAN-13
      - EAN-8
      - UPC-A
      - ITF (Interleaved 2 of 5)
      - ISBN-13
      - ISBN-10

    Phase 2 extras (UPC-E, Codabar, GS1-128, etc.) are handled
    via treepoem instead.
    """
    if barcode is None or Image is None:
        return None

    kind_norm = (kind or "").strip().lower()
    key = kind_norm.replace(" ", "").replace("-", "").replace("_", "")

    if key == "code128":
        cls_name = "code128"
    elif key in {"code39", "c39"}:
        cls_name = "code39"
    elif key == "ean13":
        cls_name = "ean13"
    elif key in {"ean8", "ean-8"}:
        cls_name = "ean8"
    elif key in {"isbn13", "isbn-13"}:
        cls_name = "ean13"
        # ISBN-13 is just EAN-13 with 978/979 prefix - validate it
        digits = "".join(ch for ch in data if ch.isdigit())
        if not digits.startswith(('978', '979')):
            return None  # Invalid ISBN-13 prefix
    elif key in {"isbn10", "isbn-10", "isbn"}:
        # Convert ISBN-10 to ISBN-13 for rendering
        try:
            digits = "".join(ch for ch in data if ch.isdigit() or ch.upper() == 'X')
            if len(digits) == 10:
                data = isbn10_to_isbn13(digits)
                cls_name = "ean13"
            else:
                return None
        except:
            return None
    elif key in {"upca", "upc"}:
        cls_name = "upc"
    elif key.startswith("itf"):
        cls_name = "itf"
    else:
        return None  # not a python-barcode type

    # EAN-13 / UPC-A / EAN-8: normalize / auto-checkdigit
    if cls_name == "ean13":
        digits = "".join(ch for ch in data if ch.isdigit())
        if len(digits) == 12:
            digits = digits + ean13_checksum(digits)
        if len(digits) != 13:
            return None
        data = digits

    if cls_name == "ean8":
        digits = "".join(ch for ch in data if ch.isdigit())
        if len(digits) == 7:
            # auto check-digit
            digits = digits + ean8_checksum(digits)
        elif len(digits) != 8:
            return None
        data = digits

    if cls_name == "upc":
        digits = "".join(ch for ch in data if ch.isdigit())
        if len(digits) == 11:
            digits = digits + upca_checksum(digits)
        if len(digits) != 12:
            return None
        data = digits

    try:
        bc_class = barcode.get_barcode_class(cls_name)
    except Exception:
        return None

    writer = ImageWriter()
    writer_options = {
        "module_width": 0.2,
        "module_height": 15.0,
        "quiet_zone": 3.0,
        "font_size": 0,
        "text_distance": 1.0,
    }

    try:
        bc = bc_class(data, writer=writer)
        pil_img = bc.render(writer_options)
        return _pil_to_qimage(pil_img)
    except Exception:
        return None


# --- QR (qrcode) ----------------------------------------------------------


def _render_qr(kind: str, data: str) -> Optional[QtGui.QImage]:
    """
    Render QR Code with the lightweight `qrcode` lib (fast, no Ghostscript).
    """
    if qrcode is None or Image is None:
        return None

    kind_norm = (kind or "").strip().lower()
    if "qr" not in kind_norm:
        return None

    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        pil_img = qr.make_image(fill_color="black", back_color="white").convert(
            "RGBA"
        )
        return _pil_to_qimage(pil_img)
    except Exception:
        return None


# --- Phase 2 & advanced (treepoem / BWIPP) -------------------------------


def _render_treepoem(kind: str, data: str) -> Optional[QtGui.QImage]:
    """
    Phase 2 / advanced symbologies via treepoem + Ghostscript.
    Returns a QImage or None on error/unavailable.
    """
    if treepoem is None or Image is None:
        return None

    key = (kind or "").strip().lower().replace(" ", "").replace("-", "")

    # Map UI names -> BWIPP / treepoem barcode_type names
    mapping = {
        # 1D extras
        "upce": "upce",
        "codabar": "rationalizedCodabar",
        "gs1128": "gs1-128",
        "gs1_128": "gs1-128",
        "gs1128": "gs1-128",

        # ITF-14 (treepoem already knows basic ITF via python-barcode)
        "itf14": "itf14",

        # 2D
        "datamatrix": "datamatrix",
        "pdf417": "pdf417",
        "aztec": "azteccode",          # or "azteccode" depending on your version
        "gs1datamatrix": "gs1datamatrix",
    }

    barcode_type = mapping.get(key)
    if not barcode_type:
        return None  # not a treepoem type

    try:
        img = treepoem.generate_barcode(
            barcode_type=barcode_type,
            data=data,
        )
    except Exception:
        return None

    try:
        pil_img = img.convert("RGBA")
        return _pil_to_qimage(pil_img)
    except Exception:
        return None





# --- Public API -----------------------------------------------------------

def render_barcode_to_qimage(kind: str, data: str) -> QtGui.QImage:
    """
    Supported (assuming libs installed):

      python-barcode:
        - Code128
        - Code39
        - EAN-13 (auto check digit if 12 digits)
        - EAN-8 (auto check digit if 7 digits)
        - UPC-A  (auto check digit if 11 digits)
        - ITF
        - ISBN-13 (EAN-13 with 978/979 prefix)
        - ISBN-10 (converted to EAN-13 for rendering)

      treepoem:
        - UPC-E
        - Codabar
        - GS1-128
        - ITF-14
        - Data Matrix
        - PDF417
        - Aztec
        - GS1 DataMatrix
        - ISSN (rendered as EAN-13)

      qrcode:
        - QR Code

    If everything fails, we return a simple text placeholder image.
    """
    kind = (kind or "").strip() or "Code128"
    data = data or ""

    # ---- cache lookup ----------------------------------------------------
    key = (kind.lower(), data)
    cached = _BARCODE_QIMAGE_CACHE.get(key)
    if cached is not None and not cached.isNull():
        return cached

    qimg: Optional[QtGui.QImage] = None

    # 1) QR via qrcode (fast)
    qimg = _render_qr(kind, data)
    if qimg is None:
        # 2) Simple 1D via python-barcode
        qimg = _render_1d_barcode(kind, data)
    if qimg is None:
        # 3) Advanced / Phase 2 via treepoem
        qimg = _render_treepoem(kind, data)

    if qimg is None or qimg.isNull():
        # 4) Fallback: text-only placeholder (not scannable)
        width = 400
        height = 120
        img = QtGui.QImage(width, height, QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtGui.QColor("white"))

        p = QtGui.QPainter(img)
        try:
            p.setPen(QtGui.QPen(QtGui.QColor("black")))
            f = QtGui.QFont("Arial", 12)
            p.setFont(f)
            text = f"{kind}: {data}"
            p.drawText(10, height // 2, text)
        finally:
            p.end()

        qimg = img

    # Optional sanity clamp so we don't keep absurdly huge images
    MAX_SIDE = 1200
    if qimg.width() > MAX_SIDE or qimg.height() > MAX_SIDE:
        qimg = qimg.scaled(
            MAX_SIDE,
            MAX_SIDE,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )

    # store in cache and return
    _BARCODE_QIMAGE_CACHE[key] = qimg
    return qimg



# --- Validation helpers ---------------------------------------------------


def _validate_code128(data: str) -> str:
    data = data or ""
    if not data:
        raise BarcodeValidationError("Code 128 data cannot be empty.")
    for ch in data:
        if ord(ch) < 32 or ord(ch) > 126:
            raise BarcodeValidationError(
                f"Code 128 only supports printable ASCII (32–126). Offending char: {repr(ch)}"
            )
    return data


def _validate_code39(data: str) -> str:
    data = (data or "").strip().upper()
    if not data:
        raise BarcodeValidationError("Code 39 data cannot be empty.")
    allowed = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ -. $/+%"
    for ch in data:
        if ch not in allowed:
            raise BarcodeValidationError(
                f"Code 39 does not allow {repr(ch)}. Allowed: A–Z, 0–9, space, - . $ / + %"
            )
    if "*" in data:
        raise BarcodeValidationError(
            "Do not include '*' in Code 39 data (it's reserved for start/stop)."
        )
    return data


def _validate_itf(data: str) -> str:
    data = (data or "").strip()
    if not data:
        raise BarcodeValidationError("ITF data cannot be empty.")
    if not data.isdigit():
        raise BarcodeValidationError("ITF (Interleaved 2 of 5) supports digits only.")
    if len(data) % 2 != 0:
        raise BarcodeValidationError("ITF requires an even number of digits.")
    return data


def _validate_ean13(data: str, auto_checksum: bool = True) -> str:
    data = (data or "").strip()
    if not data:
        raise BarcodeValidationError("EAN-13 data cannot be empty.")
    if not data.isdigit():
        raise BarcodeValidationError("EAN-13 supports digits only.")
    if len(data) not in (12, 13):
        raise BarcodeValidationError("EAN-13 must be 12 or 13 digits long.")

    if len(data) == 12:
        if not auto_checksum:
            raise BarcodeValidationError(
                "EAN-13 is 12 digits + 1 check digit. Provide 13 digits or enable auto checksum."
            )
        cd = ean13_checksum(data)
        return data + cd

    body = data[:-1]
    cd = data[-1]
    expected = ean13_checksum(body)
    if cd != expected:
        raise BarcodeValidationError(
            f"Invalid EAN-13 check digit: got {cd}, expected {expected}."
        )
    return data


def _validate_upca(data: str, auto_checksum: bool = True) -> str:
    data = (data or "").strip()
    if not data:
        raise BarcodeValidationError("UPC-A data cannot be empty.")
    if not data.isdigit():
        raise BarcodeValidationError("UPC-A supports digits only.")
    if len(data) not in (11, 12):
        raise BarcodeValidationError("UPC-A must be 11 or 12 digits long.")

    if len(data) == 11:
        if not auto_checksum:
            raise BarcodeValidationError(
                "UPC-A is 11 digits + 1 check digit. Provide 12 digits or enable auto checksum."
            )
        cd = upca_checksum(data)
        return data + cd

    body = data[:-1]
    cd = data[-1]
    expected = upca_checksum(body)
    if cd != expected:
        raise BarcodeValidationError(
            f"Invalid UPC-A check digit: got {cd}, expected {expected}."
        )
    return data

def _validate_ean8(data: str, auto_checksum: bool = True) -> str:
    """
    Validate EAN-8 barcode data.
    
    Args:
        data: 7 or 8 digit string
        auto_checksum: If True, auto-generate checksum for 7-digit input
    
    Returns:
        Normalized 8-digit EAN-8 string
    
    Raises:
        BarcodeValidationError: If data is invalid
    """
    data = (data or "").strip()
    if not data:
        raise BarcodeValidationError("EAN-8 data cannot be empty.")
    if not data.isdigit():
        raise BarcodeValidationError("EAN-8 supports digits only.")
    if len(data) not in (7, 8):
        raise BarcodeValidationError("EAN-8 must be 7 or 8 digits long.")
    
    if len(data) == 7:
        if not auto_checksum:
            raise BarcodeValidationError(
                "EAN-8 is 7 digits + 1 check digit. Provide 8 digits or enable auto checksum."
            )
        cd = ean8_checksum(data)
        return data + cd
    
    # Validate existing checksum
    body = data[:-1]
    cd = data[-1]
    expected = ean8_checksum(body)
    if cd != expected:
        raise BarcodeValidationError(
            f"Invalid EAN-8 check digit: got {cd}, expected {expected}."
        )
    return data


def _validate_isbn13(data: str) -> str:
    """
    Validate ISBN-13 (which is EAN-13 with 978/979 prefix).
    
    Args:
        data: 12 or 13 digit string starting with 978 or 979
    
    Returns:
        Normalized 13-digit ISBN-13 string
    
    Raises:
        BarcodeValidationError: If data is invalid
    """
    data = (data or "").strip().replace('-', '').replace(' ', '')
    
    # ISBN-13 must start with 978 or 979 (Bookland prefix)
    if not data.startswith(('978', '979')):
        raise BarcodeValidationError(
            "ISBN-13 must start with 978 or 979 (Bookland prefix)."
        )
    
    # Use EAN-13 validation (ISBN-13 is just EAN-13 with special prefix)
    return _validate_ean13(data, auto_checksum=True)


def _validate_isbn10(data: str) -> str:
    """
    Validate ISBN-10 with specific checksum algorithm.
    
    Args:
        data: 10-character string (9 digits + check digit 0-9 or X)
    
    Returns:
        Normalized 10-character ISBN-10 string
    
    Raises:
        BarcodeValidationError: If data is invalid
    """
    data = data.strip().upper().replace('-', '').replace(' ', '')
    
    if len(data) != 10:
        raise BarcodeValidationError(f"ISBN-10 must be 10 characters (got {len(data)}).")
    
    # First 9 must be digits
    if not data[:9].isdigit():
        raise BarcodeValidationError("First 9 characters of ISBN-10 must be digits.")
    
    # Last character can be digit or 'X'
    if not (data[9].isdigit() or data[9] == 'X'):
        raise BarcodeValidationError("ISBN-10 check digit must be 0-9 or X.")
    
    # Validate checksum
    total = sum((10 - i) * int(data[i]) for i in range(9))
    check = data[9]
    check_value = 10 if check == 'X' else int(check)
    
    if (total + check_value) % 11 != 0:
        expected = isbn10_checksum(data[:9])
        raise BarcodeValidationError(
            f"Invalid ISBN-10 checksum (expected {expected}, got {check})."
        )
    
    return data


def _validate_issn(data: str) -> str:
    """
    Validate ISSN (International Standard Serial Number).
    Used for magazines, journals, and periodicals.
    
    Args:
        data: 8-character string (7 digits + check digit 0-9 or X)
    
    Returns:
        Normalized 8-character ISSN string
    
    Raises:
        BarcodeValidationError: If data is invalid
    """
    data = data.strip().upper().replace('-', '').replace(' ', '')
    
    if len(data) != 8:
        raise BarcodeValidationError(f"ISSN must be 8 characters (got {len(data)}).")
    
    # First 7 must be digits
    if not data[:7].isdigit():
        raise BarcodeValidationError("First 7 characters of ISSN must be digits.")
    
    # Last character can be digit or 'X'
    if not (data[7].isdigit() or data[7] == 'X'):
        raise BarcodeValidationError("ISSN check character must be 0-9 or X.")
    
    # Validate checksum
    total = sum((8 - i) * int(data[i]) for i in range(7))
    check_value = 10 if data[7] == 'X' else int(data[7])
    
    if (total + check_value) % 11 != 0:
        expected = issn_checksum(data[:7])
        raise BarcodeValidationError(
            f"Invalid ISSN checksum (expected {expected}, got {data[7]})."
        )
    
    return data


def _validate_upce(data: str) -> str:
    """
    UPC-E validation.

    Rules we enforce here:
      - digits only
      - length 6, 7 or 8
      - if length >= 7, first digit is the number system (usually 0 or 1)

    We *don't* recompute the check digit for UPC-E (that requires full
    UPC-A expansion), but this still catches the most common mistakes.
    """
    data = (data or "").strip()
    if not data:
        raise BarcodeValidationError("UPC-E data cannot be empty.")
    if not data.isdigit():
        raise BarcodeValidationError("UPC-E supports digits only.")

    if len(data) not in (6, 7, 8):
        raise BarcodeValidationError(
            "UPC-E must be 6, 7 or 8 digits long.\n"
            "• 6 digits = payload only\n"
            "• 7 digits = number system (0 or 1) + 6-digit payload\n"
            "• 8 digits = number system + 6-digit payload + check digit"
        )

    if len(data) >= 7:
        number_system = data[0]
        if number_system not in ("0", "1"):
            # Some environments allow 2, but 0/1 is the typical retail use.
            raise BarcodeValidationError(
                f"UPC-E number system should usually be 0 or 1 (got {number_system}).\n"
                "If you intentionally need a different system digit, encode it as UPC-A instead."
            )

    # We intentionally do not try to validate the UPC-E check digit here
    # because it requires fully expanding to UPC-A according to the
    # compression rules. The scanner / BWIPP will still enforce it.
    return data



def _validate_codabar(data: str) -> str:
    """
    Codabar: digits 0–9, - : $ / . + and A–D as start/stop.
    We enforce:
      - non-empty
      - allowed characters only
      - first and last character are A, B, C or D
    """
    data = (data or "").strip().upper()
    if not data:
        raise BarcodeValidationError("Codabar data cannot be empty.")

    allowed = "0123456789-:$/.+ABCD"
    for ch in data:
        if ch not in allowed:
            raise BarcodeValidationError(
                f"Codabar does not allow {repr(ch)}.\n"
                "Allowed: 0–9, - : $ / . + and A–D (start/stop)."
            )

    if len(data) < 2 or data[0] not in "ABCD" or data[-1] not in "ABCD":
        raise BarcodeValidationError(
            "Codabar should start and end with A, B, C, or D (start/stop characters).\n"
            "Example: A123456A"
        )

    return data



def _validate_qr(data: str) -> str:
    data = data or ""
    if not data.strip():
        raise BarcodeValidationError("QR Code data cannot be empty.")
    if len(data) > 500:
        raise BarcodeValidationError("QR Code data too long (>500 chars).")
    return data


def _validate_datamatrix(data: str) -> str:
    """
    Data Matrix: very flexible, so we just enforce:
      - non-empty (non-whitespace)
      - not absurdly long
    """
    data = data or ""
    if not data.strip():
        raise BarcodeValidationError("Data Matrix data cannot be empty.")
    if len(data) > 2000:
        raise BarcodeValidationError("Data Matrix payload too long (>2000 characters).")
    return data



def _validate_pdf417(data: str) -> str:
    """
    PDF417: also flexible; we enforce:
      - non-empty
      - reasonable max length
    """
    data = data or ""
    if not data.strip():
        raise BarcodeValidationError("PDF417 data cannot be empty.")
    if len(data) > 1800:
        raise BarcodeValidationError("PDF417 payload too long (>1800 characters).")
    return data



def _validate_aztec(data: str) -> str:
    """
    Aztec Code: flexible; we enforce:
      - non-empty
      - reasonable length
    """
    data = data or ""
    if not data.strip():
        raise BarcodeValidationError("Aztec Code data cannot be empty.")
    if len(data) > 3000:
        raise BarcodeValidationError("Aztec Code payload too long (>3000 characters).")
    return data



def _validate_gs1_like(data: str) -> str:
    """
    Very light-weight GS1 syntax checker for:
      - GS1-128
      - GS1 DataMatrix

    We support either:
      - raw FNC1-separated data (we don't see the FNC1 here), or
      - AI in parentheses: (01)12345678901231(17)250101(10)BATCH1

    This is intentionally not a full GS1 validator; it just catches
    obviously broken AI syntax and absurd length.
    """
    data = data or ""
    if not data.strip():
        raise BarcodeValidationError("GS1 data cannot be empty.")

    # Soft length cap
    if len(data) > 512:
        raise BarcodeValidationError("GS1 data too long (>512 characters).")

    # If no parentheses at all, accept as-is (could be FNC1-separated/operator-specific).
    if "(" not in data and ")" not in data:
        return data

    # Basic AI syntax check: '(AI)' where AI is 2–4 digits.
    depth = 0
    i = 0
    while i < len(data):
        ch = data[i]
        if ch == "(":
            depth += 1
            j = i + 1
            ai_digits: list[str] = []
            while j < len(data) and data[j].isdigit():
                ai_digits.append(data[j])
                j += 1
            if not ai_digits or not (2 <= len(ai_digits) <= 4) or j >= len(data) or data[j] != ")":
                raise BarcodeValidationError(
                    "GS1 AI syntax looks invalid near position "
                    f"{i}. Expected '(AI)' where AI is 2–4 digits, e.g. (01), (17), (10)."
                )
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise BarcodeValidationError("Unbalanced ')' in GS1 data.")
        i += 1

    if depth != 0:
        raise BarcodeValidationError("Unbalanced '(' / ')' in GS1 data.")

    return data

def _barcode_help_text(self, kind: str) -> str:
    k = (kind or "").lower()

    if k in ("upc-e", "upce"):
        return (
            "UPC-E:\n"
            "• 6 digits = payload only\n"
            "• 7 digits = number system (0 or 1) + payload\n"
            "• 8 digits = number system + payload + check digit"
        )
    if k in ("upc-a", "upca", "upc"):
        return "UPC-A: 11 or 12 digits; check digit is validated automatically."
    if k in ("ean-13", "ean13"):
        return "EAN-13: 12 or 13 digits; check digit is validated automatically."
    if k in ("ean-8", "ean8"):
        return "EAN-8: 7 or 8 digits; check digit is validated automatically."
    if k in ("code39", "code 39", "code-39"):
        return "Code 39: A–Z, 0–9, space, - . $ / + % (no * in data)."
    if k in ("itf", "itf-14"):
        return "ITF / ITF-14: numeric only, even number of digits (pairs are interleaved)."
    if k in ("codabar", "codebar"):
        return (
            "Codabar: data must start and end with A, B, C, or D.\n"
            "Allowed chars: 0–9, - : $ / . + and A–D."
        )
    if k in ("isbn-13", "isbn13"):
        return "ISBN-13: 13 digits starting with 978 or 979; used for books."
    if k in ("isbn-10", "isbn10", "isbn"):
        return "ISBN-10: 10 characters (9 digits + check digit 0-9 or X); used for older books."
    if k == "issn":
        return "ISSN: 8 characters (7 digits + check digit 0-9 or X); used for periodicals."
    if k == "data matrix" or k == "datamatrix":
        return "Data Matrix: free-form text; keep it under ~2000 characters."
    if k == "pdf417":
        return "PDF417: free-form text; best kept under ~1800 characters."
    if k == "aztec":
        return "Aztec Code: free-form text; best kept under ~3000 characters."
    if k in ("gs1-128", "gs1128"):
        return "GS1-128: use GS1 AIs like (01)…(17)… or your scanner's GS1 format."
    if k in ("gs1 datamatrix", "gs1datamatrix"):
        return "GS1 DataMatrix: GS1 AIs like (01)…(17)…; scanner must be set for GS1."

    return ""

def get_supported_barcode_types() -> list[str]:
    """
    Get list of all supported barcode types.
    Returns display names in user-friendly format.
    
    Returns:
        List of barcode type names suitable for UI dropdowns
    
    Example:
        types = get_supported_barcode_types()
        # ['Code 128', 'Code 39', 'EAN-13', ...]
    """
    return [
        "Code 128",
        "Code 39",
        "EAN-13",
        "EAN-8",
        "UPC-A",
        "UPC-E",
        "ITF",
        "ITF-14",
        "ISBN-13",
        "ISBN-10",
        "ISSN",
        "Codabar",
        "QR Code",
        "Data Matrix",
        "PDF417",
        "Aztec Code",
        "GS1-128",
        "GS1 DataMatrix",
    ]

def validate_barcode_data(kind: str, data: str) -> str:
    """
    Main entry point for data validation.

    Returns normalized data, or raises BarcodeValidationError.
    """
    kind_norm = (kind or "").strip().lower()
    key = kind_norm.replace(" ", "").replace("-", "").replace("_", "")

    if key == "code128":
        return _validate_code128(data)
    if key == "code39":
        return _validate_code39(data)
    if key in {"itf", "itf14", "interleaved2of5", "i2of5"}:
        return _validate_itf(data)
    if key == "ean13":
        return _validate_ean13(data)
    if key in {"ean8", "ean-8"}:
        return _validate_ean8(data)
    if key in {"upca", "upc"}:
        return _validate_upca(data)
    if key in {"isbn13", "isbn-13"}:
        return _validate_isbn13(data)
    if key in {"isbn10", "isbn-10", "isbn"}:
        return _validate_isbn10(data)
    if key == "issn":
        return _validate_issn(data)
    if key == "upce":
        return _validate_upce(data)
    if key in {"codabar", "codebar"}:
        return _validate_codabar(data)
    if key == "datamatrix":
        return _validate_datamatrix(data)
    if key == "pdf417":
        return _validate_pdf417(data)
    if key == "aztec":
        return _validate_aztec(data)
    if key in {"gs1128", "gs1datamatrix"}:
        return _validate_gs1_like(data)
    if "qr" in key:
        return _validate_qr(data)

    # default: just enforce non-empty
    data = data or ""
    if not data:
        raise BarcodeValidationError(
            f"Data cannot be empty for barcode type {kind!r}."
        )
    return data

