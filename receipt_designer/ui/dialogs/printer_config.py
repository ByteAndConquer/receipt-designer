# receipt_designer/ui/dialogs/printer_config.py
"""Dialog for editing printer configuration."""
from __future__ import annotations

from PySide6 import QtWidgets


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

    result: dict | None = None

    def _apply():
        nonlocal result
        label = cut_mode.currentText()
        result = {
            "interface": iface_rev.get(iface.currentText(), "network"),
            "host": host.text().strip(),
            "port": int(port.value()),
            "darkness": int(darkness.value()),
            "dpi": int(dpi.value()),
            "width_px": int(width_px.value()),
            "threshold": int(threshold.value()),
            "cut_mode": {"Full": "full", "Partial": "partial", "None": "none"}[label],
            "timeout": float(timeout_sb.value()),
            "profile": profile_edit.text().strip() or "TM-T88IV",
        }
        d.accept()

    btns.accepted.connect(_apply)
    btns.rejected.connect(d.reject)
    d.exec()

    return result
