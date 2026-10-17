"""Unit tests for USB id parsing and device listing helpers."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from receipt_designer.printing.usb_devices import (
    UsbDeviceInfo,
    discover_usb_endpoints,
    format_usb_endpoint,
    format_usb_id,
    list_usb_devices,
    parse_usb_id,
    sanitize_usb_display_text,
)


class TestParseUsbId:
    def test_none_and_empty(self):
        assert parse_usb_id(None) is None
        assert parse_usb_id("") is None
        assert parse_usb_id("   ") is None

    def test_int_passthrough(self):
        assert parse_usb_id(0x0416) == 0x0416

    def test_hex_with_prefix(self):
        assert parse_usb_id("0x0416") == 0x0416
        assert parse_usb_id("0x81") == 0x81

    def test_decimal_string(self):
        assert parse_usb_id("1046") == 1046

    def test_bare_hex(self):
        assert parse_usb_id("0416") == 0x0416

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_usb_id("not-a-id")

    def test_out_of_range(self):
        with pytest.raises(ValueError):
            parse_usb_id(0x10000)
        with pytest.raises(ValueError):
            parse_usb_id("0x1FF", max_value=0xFF)


class TestFormatUsbId:
    def test_format_vid_pid(self):
        assert format_usb_id(0x0416) == "0x0416"
        assert format_usb_endpoint(0x81) == "0x81"
        assert format_usb_endpoint(0x03) == "0x03"


class TestListUsbDevices:
    def test_raises_without_pyusb(self):
        with patch("receipt_designer.printing.usb_devices.usb", None):
            with pytest.raises(RuntimeError, match="pyusb"):
                list_usb_devices()

    def test_lists_and_sorts_devices(self):
        class FakeEp:
            def __init__(self, addr):
                self.bEndpointAddress = addr

        class FakeIntf(list):
            pass

        # OUT=0x03, IN=0x81
        intf = FakeIntf([FakeEp(0x03), FakeEp(0x81)])
        cfg = {0: intf}
        # Make cfg iterable over interfaces
        cfg_iter = SimpleNamespace()
        cfg_iter.__iter__ = lambda self: iter([intf])

        def make_dev(vid, pid, product=""):
            dev = MagicMock()
            dev.idVendor = vid
            dev.idProduct = pid
            dev.manufacturer.return_value = "Maker"
            dev.product.return_value = product
            dev.get_active_configuration.return_value = [intf]
            return dev

        devices = [
            make_dev(0x1000, 0x0002, "B"),
            make_dev(0x0416, 0x5011, "Printer"),
        ]

        fake_usb = MagicMock()
        fake_usb.core.find.return_value = devices
        fake_usb.util.endpoint_direction.side_effect = lambda addr: (
            fake_usb.util.ENDPOINT_OUT if (addr & 0x80) == 0 else fake_usb.util.ENDPOINT_IN
        )
        fake_usb.util.ENDPOINT_OUT = 0
        fake_usb.util.ENDPOINT_IN = 1

        with patch("receipt_designer.printing.usb_devices.usb", fake_usb):
            result = list_usb_devices()

        assert len(result) == 2
        assert result[0].vendor_id == 0x0416
        assert result[0].product_id == 0x5011
        assert result[0].product == "Printer"
        assert result[0].out_ep == 0x03
        assert result[0].in_ep == 0x81
        assert "0x0416" in result[0].label


class TestDiscoverUsbEndpoints:
    def test_returns_none_without_pyusb(self):
        with patch("receipt_designer.printing.usb_devices.usb", None):
            assert discover_usb_endpoints(0x0416, 0x5011) == (None, None)

    def test_device_missing(self):
        fake_usb = MagicMock()
        fake_usb.core.find.return_value = None
        with patch("receipt_designer.printing.usb_devices.usb", fake_usb):
            assert discover_usb_endpoints(1, 2) == (None, None)


class TestUsbDeviceInfoLabel:
    def test_label_falls_back(self):
        info = UsbDeviceInfo(vendor_id=1, product_id=2)
        assert info.label.endswith("USB device")

    def test_printer_tag(self):
        info = UsbDeviceInfo(vendor_id=1, product_id=2, product="X", is_printer_class=True)
        assert "[printer]" in info.label


class TestSanitizeUsbDisplayText:
    def test_strips_control_and_bidi(self):
        dirty = "Good\x00Printer\u202e"
        assert sanitize_usb_display_text(dirty) == "GoodPrinter"

    def test_truncates(self):
        assert len(sanitize_usb_display_text("x" * 200, max_len=10)) == 10


class TestListUsbDevicesNoConfigure:
    def test_scan_does_not_set_configuration(self):
        """Device listing must not call set_configuration (avoids disrupting peripherals)."""
        dev = MagicMock()
        dev.idVendor = 0x0416
        dev.idProduct = 0x5011
        dev.manufacturer.return_value = "Maker"
        dev.product.return_value = "Printer"
        dev.bDeviceClass = 0x07
        # No active configuration — would previously trigger set_configuration
        dev.get_active_configuration.side_effect = Exception("no config")

        fake_usb = MagicMock()
        fake_usb.core.find.return_value = [dev]
        fake_usb.util.ENDPOINT_OUT = 0
        fake_usb.util.ENDPOINT_IN = 1

        with patch("receipt_designer.printing.usb_devices.usb", fake_usb):
            result = list_usb_devices()

        assert len(result) == 1
        dev.set_configuration.assert_not_called()
        assert result[0].out_ep is None
        assert result[0].in_ep is None
