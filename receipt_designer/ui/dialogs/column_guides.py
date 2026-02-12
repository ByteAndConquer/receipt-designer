# receipt_designer/ui/dialogs/column_guides.py
"""
Column guides dialog — prompts the user for column count, mode, and width.

This module must NOT import main_window_impl to avoid circular imports.
"""
from __future__ import annotations

from typing import Optional

from PySide6 import QtWidgets


class ColumnGuidesResult:
    """Immutable result from the column guides dialog."""

    __slots__ = ("num_cols", "mode", "custom_width_mm")

    def __init__(self, num_cols: int, mode: str, custom_width_mm: float):
        self.num_cols = num_cols
        self.mode = mode
        self.custom_width_mm = custom_width_mm


def show_column_guides_dialog(
    parent: QtWidgets.QWidget | None = None,
) -> Optional[ColumnGuidesResult]:
    """Show a dialog to configure column guides.

    Returns a :class:`ColumnGuidesResult` with the user's choices,
    or ``None`` if the dialog was cancelled.

    Parameters
    ----------
    parent:
        Parent widget for the dialog (typically the main window).
    """
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("Set Column Guides")
    layout = QtWidgets.QFormLayout(dialog)

    # Number of columns
    sb_cols = QtWidgets.QSpinBox()
    sb_cols.setRange(1, 10)
    sb_cols.setValue(3)
    layout.addRow("Number of columns:", sb_cols)

    # Column width mode
    combo_mode = QtWidgets.QComboBox()
    combo_mode.addItems(["Equal width", "Custom width"])
    layout.addRow("Column mode:", combo_mode)

    # Custom width input (hidden by default)
    sb_width = QtWidgets.QDoubleSpinBox()
    sb_width.setRange(5.0, 200.0)
    sb_width.setValue(20.0)
    sb_width.setSuffix(" mm")
    sb_width.setDecimals(1)
    lbl_width = QtWidgets.QLabel("Column width:")
    layout.addRow(lbl_width, sb_width)
    lbl_width.setVisible(False)
    sb_width.setVisible(False)

    # Show/hide custom width based on mode
    def on_mode_changed(mode: str) -> None:
        is_custom = mode == "Custom width"
        lbl_width.setVisible(is_custom)
        sb_width.setVisible(is_custom)

    combo_mode.currentTextChanged.connect(on_mode_changed)

    # Buttons
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addRow(buttons)

    if dialog.exec() != QtWidgets.QDialog.Accepted:
        return None

    return ColumnGuidesResult(
        num_cols=sb_cols.value(),
        mode=combo_mode.currentText(),
        custom_width_mm=sb_width.value(),
    )
