from __future__ import annotations
import sys
from pathlib import Path
from PySide6 import QtGui
from PySide6.QtWidgets import QApplication
from .ui.main_window import MainWindow


def _get_base_path() -> Path:
    """
    Get the base path for the application.

    When frozen with PyInstaller, assets are extracted to sys._MEIPASS.
    When running from source, use the package directory.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running as frozen PyInstaller bundle
        return Path(sys._MEIPASS)
    else:
        # Running from source
        return Path(__file__).resolve().parent


def resource_path(rel: str) -> Path:
    """
    Get the absolute path to a resource file.

    Works both when running from source and when frozen with PyInstaller.

    Args:
        rel: Relative path from the receipt_designer package root
             (e.g., "assets/icons/ReceiptDesigner.png")

    Returns:
        Absolute Path to the resource
    """
    return _get_base_path() / rel


# Icon candidates in priority order
ICON_CANDIDATES = [
    "ReceiptDesigner128x128.ico",
    "ReceiptDesigner64x64.ico",
    "ReceiptDesigner32x32.ico",
    "ReceiptDesigner.png",
    "favicon.ico",
]


def _load_app_icon() -> QtGui.QIcon:
    """Try to load an icon from assets/icons."""
    icon_dir = resource_path("assets/icons")
    for name in ICON_CANDIDATES:
        candidate = icon_dir / name
        if candidate.exists():
            return QtGui.QIcon(str(candidate))
    # Fallback: empty icon if nothing found (log for debugging frozen builds)
    if getattr(sys, 'frozen', False):
        print(f"[ReceiptDesigner] Warning: No icon found in {icon_dir}", file=sys.stderr)
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
