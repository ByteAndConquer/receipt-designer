# receipt_designer/ui/dialogs/printer_config.py
"""Dialog for editing printer configuration."""
from __future__ import annotations

from PySide6 import QtWidgets

from receipt_designer.printing.usb_devices import (
    MAX_ENDPOINT,
    format_usb_endpoint,
    format_usb_id,
    list_usb_devices,
    parse_usb_id,
)


def show_printer_config_dialog(
    printer_cfg: dict,
    parent: QtWidgets.QWidget | None = None,
) -> dict | None:
    """
    Show a modal dialog to edit printer settings.

    *printer_cfg* is read for current values but is **not** mutated.
    Returns a new dict of updated settings if accepted, or *None* if cancelled.
    """
    d = QtWidgets.QDialog(parent)
    d.setWindowTitle("Printer Configuration")
    form = QtWidgets.QFormLayout(d)

    iface = QtWidgets.QComboBox()
    iface_map = {
        "network": "Network (LAN)",
        "usb": "USB Direct",
        "serial": "Serial (RS-232)",
    }
    iface_rev = {v: k for k, v in iface_map.items()}
    iface.addItems(iface_map.values())
    iface.setCurrentText(
        iface_map.get(printer_cfg.get("interface", "network"), "Network (LAN)")
    )

    host = QtWidgets.QLineEdit(printer_cfg.get("host", "192.168.1.50"))
    port = QtWidgets.QSpinBox()
    port.setRange(1, 65535)
    port.setValue(int(printer_cfg.get("port", 9100)))

    usb_vid = QtWidgets.QLineEdit(str(printer_cfg.get("usb_vid") or ""))
    usb_vid.setPlaceholderText("required — e.g. 0x0416")
    usb_pid = QtWidgets.QLineEdit(str(printer_cfg.get("usb_pid") or ""))
    usb_pid.setPlaceholderText("required — e.g. 0x5011")
    usb_out = QtWidgets.QLineEdit(str(printer_cfg.get("usb_out") or ""))
    usb_out.setPlaceholderText("optional — auto-detect if empty")
    usb_in = QtWidgets.QLineEdit(str(printer_cfg.get("usb_in") or ""))
    usb_in.setPlaceholderText("optional — auto-detect if empty")
    usb_out.setToolTip("Leave blank to auto-detect the USB OUT endpoint at print time.")
    usb_in.setToolTip("Leave blank to auto-detect the USB IN endpoint at print time.")

    scan_btn = QtWidgets.QPushButton("Detect USB devices…")
    scan_btn.setToolTip("Scan connected USB devices and fill Vendor/Product IDs (and endpoints when available).")

    darkness = QtWidgets.QSpinBox()
    darkness.setRange(1, 255)
    darkness.setValue(int(printer_cfg.get("darkness", 200)))

    dpi = QtWidgets.QSpinBox()
    dpi.setRange(100, 600)
    dpi.setValue(int(printer_cfg.get("dpi", 203)))

    width_px = QtWidgets.QSpinBox()
    width_px.setRange(0, 2048)
    width_px.setValue(int(printer_cfg.get("width_px", 0)))
    width_px.setToolTip("Set to 512 to force legacy-style width. 0 disables fixed width.")

    threshold = QtWidgets.QSpinBox()
    threshold.setRange(0, 255)
    threshold.setValue(int(printer_cfg.get("threshold", 180)))

    cut_mode = QtWidgets.QComboBox()
    cut_label_map = {"full": "Full", "partial": "Partial", "none": "None"}
    cut_mode.addItems(cut_label_map.values())
    saved_cut = (printer_cfg.get("cut_mode", "partial") or "partial").lower()
    cut_mode.setCurrentText(cut_label_map.get(saved_cut, "Partial"))

    timeout_sb = QtWidgets.QDoubleSpinBox()
    timeout_sb.setRange(1.0, 120.0)
    timeout_sb.setDecimals(1)
    timeout_sb.setSingleStep(1.0)
    timeout_sb.setValue(float(printer_cfg.get("timeout", 30.0)))

    profile_edit = QtWidgets.QLineEdit(printer_cfg.get("profile", "TM-T88IV"))
    profile_edit.setPlaceholderText("e.g. TM-T88IV, default, etc.")

    form.addRow("Interface:", iface)
    form.addRow("Host:", host)
    form.addRow("Port:", port)
    form.addRow("USB Vendor ID:", usb_vid)
    form.addRow("USB Product ID:", usb_pid)
    form.addRow("USB OUT endpoint:", usb_out)
    form.addRow("USB IN endpoint:", usb_in)
    form.addRow("", scan_btn)
    form.addRow("Darkness (1–255):", darkness)
    form.addRow("DPI (fallback):", dpi)
    form.addRow("Pixel Width (0 = auto):", width_px)
    form.addRow("Threshold (0–255):", threshold)
    form.addRow("Cut mode:", cut_mode)
    form.addRow("Timeout (seconds):", timeout_sb)
    form.addRow("ESC/POS profile:", profile_edit)

    btns = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    form.addRow(btns)

    def _set_field_visible(widget: QtWidgets.QWidget, visible: bool) -> None:
        widget.setVisible(visible)
        label = form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)

    def _sync_iface_visibility() -> None:
        key = iface_rev.get(iface.currentText(), "network")
        is_net = key == "network"
        is_usb = key == "usb"
        for w in (host, port):
            _set_field_visible(w, is_net)
        for w in (usb_vid, usb_pid, usb_out, usb_in):
            _set_field_visible(w, is_usb)
        scan_btn.setVisible(is_usb)

    def _scan_usb_devices() -> None:
        try:
            devices = list_usb_devices()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                d,
                "USB scan failed",
                str(exc),
            )
            return
        if not devices:
            QtWidgets.QMessageBox.information(
                d,
                "No USB devices",
                "No USB devices were found.\n\n"
                "Check the cable/power and, on Linux, that your user can access the device "
                "(libusb / udev rules).",
            )
            return

        labels = [dev.label for dev in devices]
        chosen_label, ok = QtWidgets.QInputDialog.getItem(
            d,
            "Select USB printer",
            "Device:",
            labels,
            0,
            False,
        )
        if not ok or not chosen_label:
            return

        chosen = devices[labels.index(chosen_label)]
        usb_vid.setText(format_usb_id(chosen.vendor_id))
        usb_pid.setText(format_usb_id(chosen.product_id))
        if chosen.out_ep is not None:
            usb_out.setText(format_usb_endpoint(chosen.out_ep))
        else:
            usb_out.clear()
        if chosen.in_ep is not None:
            usb_in.setText(format_usb_endpoint(chosen.in_ep))
        else:
            usb_in.clear()

    result: dict | None = None

    def _apply():
        nonlocal result
        key = iface_rev.get(iface.currentText(), "network")
        vid = usb_vid.text().strip()
        pid = usb_pid.text().strip()
        if key == "usb" and (not vid or not pid):
            QtWidgets.QMessageBox.warning(
                d,
                "USB settings required",
                "USB Vendor ID and Product ID are required.\n\n"
                "Use “Detect USB devices…” or enter them manually (hex, e.g. 0x0416).",
            )
            return

        # Validate USB id strings before persisting so QSettings never stores junk.
        out_text = usb_out.text().strip()
        in_text = usb_in.text().strip()
        if key == "usb":
            try:
                parse_usb_id(vid)
                parse_usb_id(pid)
                if out_text:
                    parse_usb_id(out_text, max_value=MAX_ENDPOINT)
                if in_text:
                    parse_usb_id(in_text, max_value=MAX_ENDPOINT)
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(d, "Invalid USB settings", str(exc))
                return

        label = cut_mode.currentText()
        result = {
            "interface": key,
            "host": host.text().strip(),
            "port": int(port.value()),
            "usb_vid": vid,
            "usb_pid": pid,
            "usb_out": out_text,
            "usb_in": in_text,
            "darkness": int(darkness.value()),
            "dpi": int(dpi.value()),
            "width_px": int(width_px.value()),
            "threshold": int(threshold.value()),
            "cut_mode": {"Full": "full", "Partial": "partial", "None": "none"}[label],
            "timeout": float(timeout_sb.value()),
            "profile": profile_edit.text().strip() or "TM-T88IV",
        }
        d.accept()

    iface.currentTextChanged.connect(lambda _text: _sync_iface_visibility())
    scan_btn.clicked.connect(_scan_usb_devices)
    btns.accepted.connect(_apply)
    btns.rejected.connect(d.reject)
    _sync_iface_visibility()
    d.exec()

    return result
