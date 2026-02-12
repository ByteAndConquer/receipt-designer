# receipt_designer/ui/dialogs/print_preview.py
"""Print preview dialog with zoom controls."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


class PrintPreviewDialog(QtWidgets.QDialog):
    """Modal dialog showing print preview with zoom controls."""

    def __init__(self, image: QtGui.QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Print Preview")
        self.image = image
        self._zoom = 1.0

        self._build_ui()
        self.resize(700, 900)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Info bar with zoom controls
        info_layout = QtWidgets.QHBoxLayout()
        self.lbl_info = QtWidgets.QLabel(
            f"Preview: {self.image.width()}×{self.image.height()} px"
        )
        info_layout.addWidget(self.lbl_info)
        info_layout.addStretch()

        # Zoom buttons
        btn_zoom_out = QtWidgets.QPushButton("−")
        btn_zoom_out.setMaximumWidth(30)
        btn_zoom_out.clicked.connect(self._zoom_out)

        btn_zoom_in = QtWidgets.QPushButton("+")
        btn_zoom_in.setMaximumWidth(30)
        btn_zoom_in.clicked.connect(self._zoom_in)

        btn_zoom_fit = QtWidgets.QPushButton("Fit")
        btn_zoom_fit.clicked.connect(self._zoom_fit)

        self.lbl_zoom = QtWidgets.QLabel("100%")
        self.lbl_zoom.setMinimumWidth(50)

        info_layout.addWidget(btn_zoom_out)
        info_layout.addWidget(self.lbl_zoom)
        info_layout.addWidget(btn_zoom_in)
        info_layout.addWidget(btn_zoom_fit)

        layout.addLayout(info_layout)

        # Scrollable image display
        self.lbl_image = QtWidgets.QLabel()
        self.lbl_image.setAlignment(QtCore.Qt.AlignCenter)
        self._update_preview()

        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(self.lbl_image)
        scroll.setWidgetResizable(False)
        layout.addWidget(scroll)

        # Print / Cancel buttons
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_box.button(QtWidgets.QDialogButtonBox.Ok).setText("Print")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _update_preview(self):
        scaled = self.image.scaled(
            int(self.image.width() * self._zoom),
            int(self.image.height() * self._zoom),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation
        )
        self.lbl_image.setPixmap(QtGui.QPixmap.fromImage(scaled))
        self.lbl_zoom.setText(f"{int(self._zoom * 100)}%")

    def _zoom_in(self):
        self._zoom = min(4.0, self._zoom * 1.25)
        self._update_preview()

    def _zoom_out(self):
        self._zoom = max(0.25, self._zoom / 1.25)
        self._update_preview()

    def _zoom_fit(self):
        scroll = self.lbl_image.parent()
        if isinstance(scroll, QtWidgets.QScrollArea):
            viewport_size = scroll.viewport().size()
            w_ratio = viewport_size.width() / self.image.width()
            h_ratio = viewport_size.height() / self.image.height()
            self._zoom = min(w_ratio, h_ratio) * 0.95
            self._update_preview()
