# receipt_designer/ui/toolbox.py

from __future__ import annotations
from PySide6 import QtCore, QtWidgets


class Toolbox(QtWidgets.QWidget):
    add_text = QtCore.Signal()
    add_barcode = QtCore.Signal()
    add_image = QtCore.Signal()

    add_line = QtCore.Signal()
    add_arrow = QtCore.Signal()

    add_rect = QtCore.Signal()
    add_circle = QtCore.Signal()
    add_star = QtCore.Signal()
    add_diamond = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _make_button(self, label: str, signal: QtCore.Signal) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(label)
        btn.clicked.connect(signal.emit)      # 👈 always .emit for clarity
        btn.setMinimumHeight(32)
        btn.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )
        return btn

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # --- Text ---
        grp_text = QtWidgets.QGroupBox("Text")
        text_layout = QtWidgets.QVBoxLayout(grp_text)

        btn_text = self._make_button("Add Text", self.add_text)
        text_layout.addWidget(btn_text)

        layout.addWidget(grp_text)

        # --- Barcodes ---
        grp_bc = QtWidgets.QGroupBox("Barcodes/Images")
        bc_layout = QtWidgets.QVBoxLayout(grp_bc)

        btn_bc = self._make_button("Add Barcode", self.add_barcode)
        bc_layout.addWidget(btn_bc)

        # Add Image lives here so it matches visually / logically
        btn_image = self._make_button("Add Image", self.add_image)
        bc_layout.addWidget(btn_image)

        layout.addWidget(grp_bc)

        # --- Lines & Arrows ---
        grp_lines = QtWidgets.QGroupBox("Lines/Arrows")
        lines_layout = QtWidgets.QVBoxLayout(grp_lines)

        btn_line = self._make_button("Add Line", self.add_line)
        lines_layout.addWidget(btn_line)

        btn_arrow = self._make_button("Add Arrow", self.add_arrow)
        lines_layout.addWidget(btn_arrow)

        layout.addWidget(grp_lines)

        # --- Shapes ---
        grp_shapes = QtWidgets.QGroupBox("Shapes")
        shapes_layout = QtWidgets.QVBoxLayout(grp_shapes)

        btn_rect = self._make_button("Rectangle", self.add_rect)
        shapes_layout.addWidget(btn_rect)

        btn_circle = self._make_button("Circle", self.add_circle)
        shapes_layout.addWidget(btn_circle)

        btn_star = self._make_button("Star", self.add_star)
        shapes_layout.addWidget(btn_star)

        btn_diamond = self._make_button("Diamond", self.add_diamond)
        shapes_layout.addWidget(btn_diamond)

        layout.addWidget(grp_shapes)

        layout.addStretch(1)
