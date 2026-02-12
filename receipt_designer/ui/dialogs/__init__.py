# receipt_designer/ui/dialogs/__init__.py
"""
Dialog builders and standalone dialog classes.

Re-exports only — implementations live in sibling modules.
This module must NOT import main_window_impl to avoid circular imports.
"""
from .print_preview import PrintPreviewDialog
from .keyboard_shortcuts import show_keyboard_shortcuts_dialog
from .duplicate_offset import show_duplicate_offset_dialog
from .printer_config import show_printer_config_dialog
from .column_guides import show_column_guides_dialog

__all__ = [
    "PrintPreviewDialog",
    "show_keyboard_shortcuts_dialog",
    "show_duplicate_offset_dialog",
    "show_printer_config_dialog",
    "show_column_guides_dialog",
]
