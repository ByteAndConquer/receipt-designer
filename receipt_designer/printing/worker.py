from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui

from .backends import make_backend  # fallback if python-escpos is missing
from .exceptions import friendly_message

# Optional python-escpos support (this is what legacy used)
_ESC_POS_AVAILABLE = True
try:
    from escpos.printer import Network, Serial, Usb  # type: ignore
except Exception:
    _ESC_POS_AVAILABLE = False

# Optional Pillow for image conversion
try:
    from PIL import Image
except Exception:
    Image = None  # type: ignore


class WorkerSignals(QtCore.QObject):
    finished = QtCore.Signal()       # no-arg; UI just shows "done"
    error = QtCore.Signal(str)       # error message
    progress = QtCore.Signal(int)    # 0–100


class PrinterWorker(QtCore.QThread):
    """
    Thread that prints via python-escpos (if available) or raw ESC/POS fallback.

    payload = {
        "image": QImage or PIL.Image.Image   # for action="print"
        "config": {
            interface: "network"|"usb"|"serial",
            host/port or serial/usb settings,
            darkness: 1..255,
            threshold: 0..255 (optional),
            cut_mode: "full"|"partial"|"none",
            dpi: int,
            width_px: int,
            timeout: float,
            profile: str,
        }
    }
    """
    def __init__(self, action: str, payload=None, parent=None, *, dry_run: bool = False):
        super().__init__(parent)
        self.action = (action or "").lower()
        self.payload = payload or {}
        self.signals = WorkerSignals()
        self.dry_run = dry_run
        self.dry_run_backend = None  # set after run() if dry_run is True

    # ---------------- escpos helpers ----------------

    def _qimage_to_pil(self, qimg: QtGui.QImage):
        """
        Convert a QImage to a Pillow Image.

        Handles both older bindings (where bits() has setsize)
        and newer PySide6 where bits()/constBits() return a memoryview.
        """
        if Image is None:
            raise RuntimeError("Pillow is required to print images (pip install pillow).")
        if qimg.isNull():
            raise RuntimeError("Cannot print: QImage is null.")

        # Normalize to RGBA for a predictable layout
        qimg = qimg.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
        width = qimg.width()
        height = qimg.height()
        bytes_per_line = qimg.bytesPerLine()
        buf_len = bytes_per_line * height

        # Get raw pointer/memory
        try:
            ptr = qimg.bits()
        except AttributeError:
            ptr = qimg.constBits()

        # PySide6 returns a memoryview now; older versions had setsize()
        try:
            # Old style (sip-style) objects
            ptr.setsize(buf_len)  # type: ignore[attr-defined]
            raw = bytes(ptr)
        except AttributeError:
            # New style memoryview – slice to length and copy
            raw = bytes(ptr[:buf_len])

        # Build Pillow image with stride
        pil_img = Image.frombuffer(
            "RGBA",
            (width, height),
            raw,
            "raw",
            "RGBA",
            bytes_per_line,
            1,
        )
        return pil_img


    def _get_escpos_printer(self, cfg: dict):
        """
        Build a python-escpos printer instance using config.
        Uses profile + timeout from cfg so you can swap printers.
        """
        if not _ESC_POS_AVAILABLE:
            raise RuntimeError(
                "python-escpos library is missing. Run: pip install python-escpos"
            )

        profile = cfg.get("profile") or "TM-T88IV"
        timeout = float(cfg.get("timeout", 30.0))
        iface = (cfg.get("interface") or "network").lower()

        if iface == "network":
            host = cfg.get("host", "127.0.0.1")
            port = int(cfg.get("port", 9100))
            # Network(host, port=9100, timeout=60, profile=...)
            return Network(host, port, timeout=timeout, profile=profile)

        if iface == "usb":
            # Expect hex strings/ints for vid/pid/endpoints, same as your legacy config.
            vid = cfg.get("usb_vid")
            pid = cfg.get("usb_pid")
            ep_in = cfg.get("usb_in", "0x82")
            ep_out = cfg.get("usb_out", "0x01")
            if vid is None or pid is None:
                raise RuntimeError("USB interface requires usb_vid and usb_pid in printer config.")
            return Usb(
                int(str(vid), 16),
                int(str(pid), 16),
                0,
                int(str(ep_in), 16),
                int(str(ep_out), 16),
                profile=profile,
            )

        if iface == "serial":
            dev = cfg.get("serial_port", "COM1")
            baud = int(cfg.get("baudrate", 19200))
            # Serial(devfile, baudrate, timeout=..., profile=...)
            return Serial(dev, baudrate=baud, timeout=timeout, profile=profile)

        raise RuntimeError(f"Unknown printer interface: {iface}")

    def _run_with_escpos(self, cfg: dict):
        """
        Use python-escpos very similarly to the legacy worker:
        - convert QImage -> PIL.Image
        - resize to target_width
        - apply darkness threshold
        - send via printer.image(..., impl='bitImageRaster')
        """
        printer = None
        try:
            printer = self._get_escpos_printer(cfg)

            if self.action == "print":
                img = self.payload.get("image")
                if isinstance(img, QtGui.QImage):
                    pil_img = self._qimage_to_pil(img)
                else:
                    pil_img = img  # assume already a PIL.Image.Image

                if pil_img is None:
                    raise RuntimeError("No image supplied to PrinterWorker for action='print'.")

                # Darkness: match legacy semantics (used as a threshold)
                darkness = int(cfg.get("darkness", 180))

                # ---- FIX: handle width_px == 0 or missing ----
                raw_width = cfg.get("width_px", 0)
                try:
                    target_width = int(raw_width)
                except Exception:
                    target_width = 0
                if target_width <= 0:
                    # fall back to the current image width
                    target_width = pil_img.width

                # Choose a resampling filter that's safe across Pillow versions
                if hasattr(Image, "Resampling"):
                    resample_filter = Image.Resampling.LANCZOS
                else:
                    resample_filter = Image.LANCZOS

                print(
                    "[ESC/POS DEBUG] action=print "
                    f"img={pil_img.width}x{pil_img.height} "
                    f"target_width={target_width} darkness={darkness} "
                    f"iface={cfg.get('interface')} host={cfg.get('host')} port={cfg.get('port')}"
                )

                # Resize + threshold like legacy
                if pil_img.width != target_width:
                    w_percent = target_width / float(pil_img.width)
                    h_size = int(float(pil_img.height) * w_percent)
                    img_gray = pil_img.convert("L")
                    img_resized = img_gray.resize((target_width, h_size), resample_filter)
                    threshold = darkness
                    pil_img = img_resized.point(
                        lambda p: 255 if p > threshold else 0
                    ).convert("1")
                else:
                    pil_img = pil_img.convert("L").point(
                        lambda p: 255 if p > darkness else 0
                    ).convert("1")

                # Let escpos know about width, if the profile supports media metadata
                if hasattr(printer, "profile") and hasattr(printer.profile, "media"):
                    media = printer.profile.media
                    try:
                        if isinstance(media, dict):
                            if "width" in media and "pixels" in media["width"]:
                                media["width"]["pixels"] = target_width
                        elif hasattr(media, "width") and hasattr(media.width, "pixels"):
                            media.width.pixels = target_width
                    except Exception:
                        # non-fatal; just an optimization hint
                        pass

                # --- DEBUG: ensure we at least send *something* text-wise too ---
                # printer.text("GUI print test\n")

                # Actual print (legacy used impl="bitImageRaster")
                printer.image(pil_img, impl="bitImageRaster", center=True)

                # Cut if configured
                cut_code = (cfg.get("cut_mode") or "partial").lower()
                if cut_code != "none":
                    # python-escpos uses FULL / PART
                    mode = "FULL" if cut_code == "full" else "PART"
                    printer.cut(mode=mode)

            elif self.action == "feed":
                printer.text("\n\n\n")

            elif self.action == "cut":
                cut_code = (cfg.get("cut_mode") or "partial").lower()
                if cut_code != "none":
                    mode = "FULL" if cut_code == "full" else "PART"
                    printer.cut(mode=mode)

            else:
                raise RuntimeError(f"Unknown print action: {self.action}")

        finally:
            try:
                if printer is not None and hasattr(printer, "close"):
                    printer.close()
            except Exception:
                pass



    # ---------------- raw ESC/POS fallback (if escpos not installed) ----------------

    @staticmethod
    def _escpos_init() -> bytes:
        return b"\x1B\x40"  # ESC @

    @staticmethod
    def _escpos_cut(mode: str) -> bytes:
        m = {"full": 65, "partial": 66, "none": None}.get(mode, 66)
        if m is None:
            return b""
        return bytes([0x1D, 0x56, m, 0])

    def _run_raw_fallback(self, cfg: dict):
        """
        Simple fallback: send init + feed/cut only.
        We DO NOT raster images here; this is just to avoid crashing
        if python-escpos isn't installed.
        """
        backend = make_backend(cfg)

        if self.action == "print":
            raise RuntimeError(
                "python-escpos is not installed, so image printing is not available. "
                "Install it with: pip install python-escpos"
            )

        data = bytearray()
        data += self._escpos_init()

        if self.action == "feed":
            data += bytes([0x1B, 0x64, 3])  # ESC d n : feed 3 lines
        elif self.action == "cut":
            cut_code = (cfg.get("cut_mode") or "partial").lower()
            data += self._escpos_cut(cut_code)
        else:
            raise RuntimeError(f"Unknown print action: {self.action}")

        backend.send(bytes(data))

    # ---------------- dry-run path ----------------

    def _run_dry(self, cfg: dict):
        """Execute the action against a DryRunBackend (no hardware)."""
        from .backends import DryRunBackend

        backend = DryRunBackend()
        data = bytearray()
        data += self._escpos_init()

        if self.action == "print":
            # Simulate a minimal print payload (init + cut)
            cut_code = (cfg.get("cut_mode") or "partial").lower()
            data += self._escpos_cut(cut_code)
        elif self.action == "feed":
            data += bytes([0x1B, 0x64, 3])
        elif self.action == "cut":
            cut_code = (cfg.get("cut_mode") or "partial").lower()
            data += self._escpos_cut(cut_code)
        else:
            raise RuntimeError(f"Unknown print action: {self.action}")

        backend.send(bytes(data))
        self.dry_run_backend = backend

    # ---------------- thread entry ----------------

    def run(self):
        try:
            cfg = dict(self.payload.get("config") or {})

            print(
                "[ESC/POS DEBUG] starting worker",
                "action=", self.action,
                "escpos_available=", _ESC_POS_AVAILABLE,
                "image_lib=", (Image is not None),
                "dry_run=", self.dry_run,
            )

            if self.dry_run:
                self._run_dry(cfg)
            elif _ESC_POS_AVAILABLE and Image is not None:
                # Full legacy-style path using python-escpos
                self._run_with_escpos(cfg)
            else:
                # Minimal raw fallback
                self._run_raw_fallback(cfg)

        except Exception as e:
            self.signals.error.emit(friendly_message(e))
        finally:
            # Always emit finished once we're done/error.
            # It's okay if caller didn't connect anything.
            try:
                self.signals.finished.emit()
            except Exception:
                pass

