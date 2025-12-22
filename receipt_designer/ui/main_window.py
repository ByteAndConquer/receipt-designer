from __future__ import annotations

"""
Thin, stable wrapper around the real MainWindow implementation.

Why this exists:
- Keeps historical imports working: `from receipt_designer.ui.main_window import MainWindow`
- Provides clearer errors if `.main_window_impl` can’t be imported
- Exposes a small factory you can use from app.py, tests, etc.
"""

# Re-export + clearer error if impl fails to import
try:
    from .main_window_impl import MainWindow as _ImplMainWindow  # noqa: F401
except Exception as exc:
    raise ImportError(
        "Failed to import receipt_designer.ui.main_window_impl.MainWindow. "
        "Make sure main_window_impl.py and its dependencies (items.py, layers.py, "
        "properties.py, toolbox.py, views.py, core/*, printing/*) are present and importable."
    ) from exc


# Public alias expected by the rest of the app
class MainWindow(_ImplMainWindow):
    """Direct alias-subclass so type checkers and runtime both see MainWindow here."""
    pass


__all__ = ["MainWindow"]


def create_window() -> MainWindow:
    """Convenience factory used by launchers/tests."""
    return MainWindow()
