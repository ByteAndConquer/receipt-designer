# receipt_designer/ui/dialogs/keyboard_shortcuts.py
"""Keyboard shortcuts reference dialog."""
from __future__ import annotations

from PySide6 import QtWidgets


def show_keyboard_shortcuts_dialog(parent: QtWidgets.QWidget) -> None:
    """Display a modal dialog listing all keyboard/mouse shortcuts."""
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("Keyboard Shortcuts")

    layout = QtWidgets.QVBoxLayout(dlg)

    label = QtWidgets.QLabel(
        "<b>Keyboard & Mouse Shortcuts</b><br>"
        "<span style='color: #666;'>Handy reference for designing receipts.</span>"
    )
    layout.addWidget(label)

    table = QtWidgets.QTableWidget(dlg)
    table.setColumnCount(3)
    table.setHorizontalHeaderLabels(["Context", "Shortcut", "Action"])
    table.horizontalHeader().setStretchLastSection(True)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)

    shortcuts = [
        # Global / file
        ("Global", "Ctrl+O", "Open template"),
        ("Global", "Ctrl+S", "Save template"),
        ("Global", "Ctrl+P", "Print"),
        ("Global", "Ctrl+Z", "Undo"),
        ("Global", "Ctrl+Y", "Redo"),

        # View / navigation
        ("View", "Ctrl + Mouse Wheel", "Zoom in / out"),
        ("View", "Space + Drag", "Pan canvas"),
        ("View", "Ctrl+M", "Toggle printable margins"),

        # Insert
        ("Insert", "Ctrl+Shift+T", "Insert Text box"),
        ("Insert", "Ctrl+Shift+B", "Insert Barcode box"),
        ("Insert", "Ctrl+Shift+L", "Insert Line"),
        ("Insert", "Ctrl+Shift+R", "Insert Rectangle"),
        ("Insert", "Ctrl+Shift+C", "Insert Circle/Ellipse"),
        ("Insert", "Ctrl+Shift+S", "Insert Star"),
        ("Insert", "Ctrl+Shift+A", "Insert Arrow"),
        ("Insert", "Ctrl+Shift+D", "Insert Diamond"),

        # Layout / grouping
        ("Layout", "Ctrl+G", "Group selected items"),
        ("Layout", "Ctrl+Shift+G", "Ungroup selected groups"),

        # Editing
        ("Editing", "Delete", "Delete selected items"),
        ("Editing", "Right-click", "Context menu (duplicate, z-order, lock, hide, delete)"),
    ]

    table.setRowCount(len(shortcuts))
    for row, (context, shortcut, action) in enumerate(shortcuts):
        for col, text in enumerate((context, shortcut, action)):
            item = QtWidgets.QTableWidgetItem(text)
            if col == 1:
                # Shortcut column -> slight bold
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            table.setItem(row, col, item)

    table.resizeColumnsToContents()
    layout.addWidget(table)

    btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
    btn_box.rejected.connect(dlg.reject)
    btn_box.accepted.connect(dlg.accept)  # just in case
    layout.addWidget(btn_box)

    dlg.resize(600, 400)
    dlg.exec()
