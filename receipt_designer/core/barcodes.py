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
      - UPC-A
      - ITF (Interleaved 2 of 5)

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
    elif key in {"upca", "upc"}:
        cls_name = "upc"
    elif key.startswith("itf"):
        cls_name = "itf"
    else:
        return None  # not a python-barcode type

    # EAN-13 / UPC-A: normalize / auto-checkdigit
    if cls_name == "ean13":
        digits = "".join(ch for ch in data if ch.isdigit())
        if len(digits) == 12:
            digits = digits + ean13_checksum(digits)
        if len(digits) != 13:
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
    Render a barcode or 2D code to a QImage, with caching.

    Supported (assuming libs installed):

      python-barcode:
        - Code128
        - Code39
        - EAN-13 (auto check digit if 12 digits)
        - UPC-A  (auto check digit if 11 digits)
        - ITF

      treepoem:
        - UPC-E
        - Codabar
        - GS1-128
        - ITF-14
        - Data Matrix
        - PDF417
        - Aztec
        - GS1 DataMatrix

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
    if k in ("code39", "code 39", "code-39"):
        return "Code 39: A–Z, 0–9, space, - . $ / + % (no * in data)."
    if k in ("itf", "itf-14"):
        return "ITF / ITF-14: numeric only, even number of digits (pairs are interleaved)."
    if k in ("codabar", "codebar"):
        return (
            "Codabar: data must start and end with A, B, C, or D.\n"
            "Allowed chars: 0–9, - : $ / . + and A–D."
        )
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
    if key in {"upca", "upc"}:
        return _validate_upca(data)
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

