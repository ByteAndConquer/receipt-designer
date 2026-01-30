from __future__ import annotations
import sys
from pathlib import Path
from PySide6 import QtGui
from PySide6.QtWidgets import QApplication
from .ui.main_window import MainWindow

BASE_DIR = Path(__file__).resolve().parent          # .../receipt_designer
ICON_DIR = BASE_DIR / "assets" / "icons"            # .../receipt_designer/assets/icons

# Change this to match your actual filename
ICON_CANDIDATES = [
    "ReceiptDesigner128x128.ico",
    "ReceiptDesigner64x64.ico",
    "ReceiptDesigner32x32.ico",
    "ReceiptDesigner.png",
    "favicon.ico",  # keep as a fallback if you want
]

def _load_app_icon() -> QtGui.QIcon:
    """Try to load an icon from assets/icons."""
    for name in ICON_CANDIDATES:
        candidate = ICON_DIR / name
        if candidate.exists():
            return QtGui.QIcon(str(candidate))
    # Fallback: empty icon if nothing found
    return QtGui.QIcon()

def main():
    app = QApplication(sys.argv)

    icon = _load_app_icon()
    app.setWindowIcon(icon)

    win = MainWindow()
    win.setWindowIcon(icon)

    win.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
