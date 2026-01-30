from __future__ import annotations

import socket
from typing import Optional

try:
    import serial  # pyserial
except Exception:
    serial = None

try:
    import usb.core  # pyusb
    import usb.util
except Exception:
    usb = None  # type: ignore


class BaseBackend:
    def send(self, data: bytes) -> None:
        raise NotImplementedError


class NetworkBackend(BaseBackend):
    def __init__(self, host: str, port: int = 9100, timeout: float = 5.0):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)

    def send(self, data: bytes) -> None:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
            s.settimeout(self.timeout)
            s.sendall(data)


class SerialBackend(BaseBackend):
    def __init__(self, port: str, baudrate: int = 19200, timeout: float = 2.0):
        if serial is None:
            raise RuntimeError(
                "pyserial not installed. `pip install pyserial` to use Serial backend."
            )
        self.port = port
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)

    def send(self, data: bytes) -> None:
        ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        try:
            ser.write(data)
            ser.flush()
        finally:
            ser.close()


class USBBackend(BaseBackend):
    # Generic ESC/POS USB backend via PyUSB. Provide VID/PID and an OUT endpoint.
    def __init__(
        self,
        vendor_id: int,
        product_id: int,
        out_endpoint: Optional[int] = None,
        interface: Optional[int] = None,
    ):
        if usb is None:
            raise RuntimeError(
                "pyusb not installed. `pip install pyusb` and install a USB backend (libusb) to use USB."
            )
        self.vendor_id = int(vendor_id)
        self.product_id = int(product_id)
        self.out_ep = out_endpoint
        self.interface = interface
        self._dev = None
        self._cfg = None
        self._ep_out = None
        self._open()

    def _open(self):
        self._dev = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
        if self._dev is None:
            raise RuntimeError(f"USB device {hex(self.vendor_id)}:{hex(self.product_id)} not found.")

        self._dev.set_configuration()
        self._cfg = self._dev.get_active_configuration()
        if self.interface is not None:
            intf = self._cfg[(self.interface, 0)]
        else:
            intf = self._cfg[(0, 0)]  # default to first interface

        # Detach kernel driver if needed (Linux)
        try:
            if self._dev.is_kernel_driver_active(intf.bInterfaceNumber):  # type: ignore[attr-defined]
                self._dev.detach_kernel_driver(intf.bInterfaceNumber)     # type: ignore[attr-defined]
        except Exception:
            pass

        # Locate OUT endpoint
        if self.out_ep is not None:
            self._ep_out = usb.util.find_descriptor(intf, bEndpointAddress=self.out_ep)
        else:
            self._ep_out = next(
                (ep for ep in intf if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT),
                None
            )

        if self._ep_out is None:
            raise RuntimeError("Could not locate a USB OUT endpoint for printer.")

    def send(self, data: bytes) -> None:
        assert self._ep_out is not None
        CHUNK = 16384
        for i in range(0, len(data), CHUNK):
            self._ep_out.write(data[i:i + CHUNK])


def make_backend(cfg: dict) -> BaseBackend:
    """Factory to build a backend from your printer config dict."""
    iface = (cfg.get("interface") or "network").lower()
    if iface == "network":
        return NetworkBackend(cfg.get("host", "127.0.0.1"), int(cfg.get("port", 9100)))
    if iface == "serial":
        return SerialBackend(cfg.get("serial_port", "COM1"), int(cfg.get("baudrate", 19200)))
    if iface == "usb":
        vid = int(cfg.get("usb_vid", 0))
        pid = int(cfg.get("usb_pid", 0))
        ep = cfg.get("usb_endpoint")
        ep = int(ep) if ep is not None else None
        iface_no = cfg.get("usb_interface")
        iface_no = int(iface_no) if iface_no is not None else None
        if not (vid and pid):
            raise RuntimeError("USB backend requires usb_vid and usb_pid in config.")
        return USBBackend(vid, pid, out_endpoint=ep, interface=iface_no)
    raise ValueError(f"Unknown interface: {iface}")
