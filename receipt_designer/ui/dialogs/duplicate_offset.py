# receipt_designer/ui/dialogs/duplicate_offset.py
"""Dialog for setting the duplicate-item offset."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets


def show_duplicate_offset_dialog(
    current_offset: QtCore.QPointF,
    parent: QtWidgets.QWidget | None = None,
) -> QtCore.QPointF | None:
    """
    Show a modal dialog to edit the duplicate offset.

    Returns the new QPointF if accepted, or *None* if cancelled.
    """
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("Set Duplicate Offset")
    layout = QtWidgets.QFormLayout(dialog)

    sb_x = QtWidgets.QDoubleSpinBox()
    sb_x.setRange(-1000, 1000)
    sb_x.setValue(current_offset.x())
    sb_x.setSuffix(" px")
    sb_x.setDecimals(0)

    sb_y = QtWidgets.QDoubleSpinBox()
    sb_y.setRange(-1000, 1000)
    sb_y.setValue(current_offset.y())
    sb_y.setSuffix(" px")
    sb_y.setDecimals(0)

    layout.addRow("Horizontal offset:", sb_x)
    layout.addRow("Vertical offset:", sb_y)

    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addRow(buttons)

    if dialog.exec() == QtWidgets.QDialog.Accepted:
        return QtCore.QPointF(sb_x.value(), sb_y.value())
    return None
