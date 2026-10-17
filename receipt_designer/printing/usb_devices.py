"""USB device listing and endpoint discovery helpers (pyusb)."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Optional

try:
    import usb.core  # pyusb
    import usb.util
except Exception:  # pragma: no cover - optional dependency / backend missing
    usb = None  # type: ignore

# USB Printer class (device or interface)
_USB_CLASS_PRINTER = 0x07
MAX_VID_PID = 0xFFFF
MAX_ENDPOINT = 0xFF


def parse_usb_id(value, *, max_value: int = MAX_VID_PID) -> Optional[int]:
    """Parse a USB VID/PID/endpoint from int or hex/decimal string.

    Accepts ``0x0416``, ``0416``, ``1046``, or an int. Returns ``None`` for
    empty / missing values. Raises ``ValueError`` for non-numeric input or
    values outside ``0..max_value`` (default 16-bit for VID/PID; pass
    ``max_value=0xFF`` for endpoints).
    """
    if value is None:
        return None
    if isinstance(value, int):
        n = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            n = int(text, 0)
        except ValueError:
            # Bare hex without 0x prefix (e.g. "0416")
            try:
                n = int(text, 16)
            except ValueError as exc:
                raise ValueError(f"Invalid USB id/endpoint value: {value!r}") from exc
    if n < 0 or n > int(max_value):
        raise ValueError(
            f"USB id/endpoint out of range (0..{int(max_value)}): {value!r}"
        )
    return n


def format_usb_id(value: int) -> str:
    """Format an integer USB id as a 0xNNNN hex string."""
    return f"0x{int(value):04x}"


def format_usb_endpoint(value: int) -> str:
    """Format an endpoint address as a compact hex string (e.g. 0x81)."""
    return f"0x{int(value):02x}"


def sanitize_usb_display_text(text: str, max_len: int = 80) -> str:
    """Strip control / bidi / non-printable chars from USB descriptor strings."""
    if not text:
        return ""
    cleaned: list[str] = []
    for ch in str(text):
        cat = unicodedata.category(ch)
        if cat.startswith("C"):  # Cc, Cf, Cs, Co, Cn
            continue
        cleaned.append(ch)
    return "".join(cleaned).strip()[:max_len]


@dataclass(frozen=True)
class UsbDeviceInfo:
    vendor_id: int
    product_id: int
    manufacturer: str = ""
    product: str = ""
    in_ep: Optional[int] = None
    out_ep: Optional[int] = None
    is_printer_class: bool = False

    @property
    def label(self) -> str:
        name = self.product or self.manufacturer or "USB device"
        tag = " [printer]" if self.is_printer_class else ""
        return f"{format_usb_id(self.vendor_id)}:{format_usb_id(self.product_id)} — {name}{tag}"


def _safe_string(dev, getter_name: str) -> str:
    getter = getattr(dev, getter_name, None)
    if getter is None:
        return ""
    try:
        value = getter()
        return sanitize_usb_display_text(str(value)) if value else ""
    except Exception:
        return ""


def _device_looks_like_printer(dev) -> bool:
    """Best-effort check for USB printer class without claiming the device."""
    try:
        if int(getattr(dev, "bDeviceClass", 0) or 0) == _USB_CLASS_PRINTER:
            return True
    except Exception:
        pass
    try:
        cfg = dev.get_active_configuration()
    except Exception:
        return False
    try:
        for intf in cfg:
            if int(getattr(intf, "bInterfaceClass", 0) or 0) == _USB_CLASS_PRINTER:
                return True
    except Exception:
        return False
    return False


def _endpoints_for_device(dev, *, may_configure: bool = False) -> tuple[Optional[int], Optional[int]]:
    """Return the first bulk/interrupt IN and OUT endpoint addresses, if any.

    When *may_configure* is False (device listing), never call
    ``set_configuration()`` so scanning cannot disrupt other peripherals.
    """
    if usb is None:
        return None, None
    try:
        try:
            cfg = dev.get_active_configuration()
        except Exception:
            if not may_configure:
                return None, None
            dev.set_configuration()
            cfg = dev.get_active_configuration()
    except Exception:
        return None, None

    in_ep: Optional[int] = None
    out_ep: Optional[int] = None
    try:
        for intf in cfg:
            for ep in intf:
                addr = int(ep.bEndpointAddress)
                direction = usb.util.endpoint_direction(addr)
                if direction == usb.util.ENDPOINT_OUT and out_ep is None:
                    out_ep = addr
                elif direction == usb.util.ENDPOINT_IN and in_ep is None:
                    in_ep = addr
            if in_ep is not None and out_ep is not None:
                break
    except Exception:
        return in_ep, out_ep
    return in_ep, out_ep


def list_usb_devices() -> list[UsbDeviceInfo]:
    """List connected USB devices with best-effort name and endpoint probes.

    Raises ``RuntimeError`` if pyusb is unavailable. Permission-denied devices
    are still listed with empty names/endpoints when possible.

    Does not call ``set_configuration()`` during enumeration (read-only scan).
    Printer-class devices are sorted first.
    """
    if usb is None:
        raise RuntimeError(
            "pyusb is not available. Install it with `pip install pyusb` "
            "and ensure a libusb backend is present."
        )

    devices: list[UsbDeviceInfo] = []
    try:
        found = list(usb.core.find(find_all=True) or [])
    except Exception as exc:
        raise RuntimeError(f"Failed to scan USB devices: {exc}") from exc

    for dev in found:
        try:
            vid = int(dev.idVendor)
            pid = int(dev.idProduct)
        except Exception:
            continue
        if vid < 0 or vid > MAX_VID_PID or pid < 0 or pid > MAX_VID_PID:
            continue
        manufacturer = _safe_string(dev, "manufacturer")
        product = _safe_string(dev, "product")
        in_ep, out_ep = _endpoints_for_device(dev, may_configure=False)
        is_printer = _device_looks_like_printer(dev)
        devices.append(
            UsbDeviceInfo(
                vendor_id=vid,
                product_id=pid,
                manufacturer=manufacturer,
                product=product,
                in_ep=in_ep,
                out_ep=out_ep,
                is_printer_class=is_printer,
            )
        )

    # Printer-class first, then VID/PID
    devices.sort(
        key=lambda d: (
            0 if d.is_printer_class else 1,
            d.vendor_id,
            d.product_id,
            d.label.lower(),
        )
    )
    return devices


def discover_usb_endpoints(vendor_id: int, product_id: int) -> tuple[Optional[int], Optional[int]]:
    """Probe IN/OUT endpoints for a specific VID/PID. Returns (in_ep, out_ep).

    May call ``set_configuration()`` because this runs when the user is about
    to print to that specific device.
    """
    if usb is None:
        return None, None
    try:
        vid = parse_usb_id(vendor_id)
        pid = parse_usb_id(product_id)
    except ValueError:
        return None, None
    if vid is None or pid is None:
        return None, None
    try:
        dev = usb.core.find(idVendor=int(vid), idProduct=int(pid))
    except Exception:
        return None, None
    if dev is None:
        return None, None
    return _endpoints_for_device(dev, may_configure=True)
