"""
ui/inline_editor.py - In-place text editing overlay for canvas elements.

Provides a text editor widget that appears over a text element on the canvas,
allowing direct editing without using the properties panel.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from PySide6 import QtCore, QtGui, QtWidgets

# Import the shared display color helper
from .items import compute_display_color

if TYPE_CHECKING:
    from .items import GItem
    from .views import RulerView


class InlineTextEditor(QtWidgets.QPlainTextEdit):
    """
    A plain text editor widget used for in-place editing on the canvas.

    Signals:
        committed: Emitted when editing is finished and text should be saved.
        cancelled: Emitted when editing is cancelled (Esc pressed).
    """

    committed = QtCore.Signal(str)  # new_text
    cancelled = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self._original_text = ""

        # Basic frame setup (styling applied later by overlay controller)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)

        # Remove scrollbars for cleaner look (text wraps)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        # Make caret more visible
        self.setCursorWidth(2)

    def setOriginalText(self, text: str):
        """Store the original text for cancel/comparison."""
        self._original_text = text
        self.setPlainText(text)
        self.selectAll()

    def originalText(self) -> str:
        return self._original_text

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """Handle special keys: Enter commits, Esc cancels."""
        key = event.key()
        modifiers = event.modifiers()

        # Esc = cancel
        if key == QtCore.Qt.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return

        # Ctrl+Enter or plain Enter on single line = commit
        # For multi-line: Enter inserts newline, Ctrl+Enter commits
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if modifiers & QtCore.Qt.ControlModifier:
                # Ctrl+Enter always commits
                self.committed.emit(self.toPlainText())
                event.accept()
                return
            else:
                # Plain Enter: commit for single-line feel
                # (User can use Shift+Enter for newline if needed)
                if not (modifiers & QtCore.Qt.ShiftModifier):
                    self.committed.emit(self.toPlainText())
                    event.accept()
                    return

        super().keyPressEvent(event)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        """Commit when focus is lost (clicking elsewhere)."""
        # Only commit if we're actually losing focus to something else
        # (not just the window being deactivated)
        if event.reason() not in (QtCore.Qt.PopupFocusReason, QtCore.Qt.ActiveWindowFocusReason):
            self.committed.emit(self.toPlainText())
        super().focusOutEvent(event)


class CanvasTextEditorOverlay:
    """
    Controller for in-place text editing on the canvas.

    Manages the lifecycle of an InlineTextEditor widget positioned over
    a GItem text element. Handles:
    - Creating and positioning the editor
    - Tracking zoom/pan/scroll changes
    - Committing or cancelling edits
    - Undo integration
    """

    def __init__(self, view: RulerView):
        self._view = view
        self._editor: Optional[InlineTextEditor] = None
        self._item: Optional[GItem] = None
        self._original_text = ""
        self._is_editing = False

        # Connect to view signals for geometry updates
        # We'll update geometry when the view scrolls or transforms

    def isEditing(self) -> bool:
        """Return True if currently editing an element."""
        return self._is_editing and self._editor is not None

    def currentItem(self) -> Optional[GItem]:
        """Return the item currently being edited, or None."""
        return self._item if self._is_editing else None

    def startEditing(self, item: GItem) -> bool:
        """
        Start in-place editing on the given item.

        Args:
            item: The GItem to edit (must be a text element)

        Returns:
            True if editing started, False if item is not editable.
        """
        # Check if item is a text element
        elem = getattr(item, "elem", None)
        if elem is None:
            return False
        kind = getattr(elem, "kind", "")
        if kind != "text":
            return False

        # End any existing edit
        if self._is_editing:
            self.commitEdit()

        self._item = item
        self._original_text = getattr(elem, "text", "") or ""
        self._is_editing = True

        # Create the editor widget as a child of the viewport
        self._editor = InlineTextEditor(self._view.viewport())
        self._editor.setOriginalText(self._original_text)

        # Apply font and visual styling to match the element
        self._applyElementFont()
        self._applyEditorStyle()

        # Position the editor over the element
        self._updateGeometry()

        # Connect signals
        self._editor.committed.connect(self._onCommitted)
        self._editor.cancelled.connect(self._onCancelled)

        # Show and focus
        self._editor.show()
        self._editor.setFocus()

        # Disable item movement while editing
        item.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, False)

        return True

    def _applyElementFont(self) -> None:
        """Apply the element's font settings to the editor."""
        if self._editor is None or self._item is None:
            return

        elem = self._item.elem

        family = getattr(elem, "font_family", "Arial") or "Arial"
        size = getattr(elem, "font_size", 12) or 12
        bold = bool(getattr(elem, "bold", False))
        italic = bool(getattr(elem, "italic", False))

        font = QtGui.QFont(family, int(size))
        font.setBold(bold)
        font.setItalic(italic)

        self._editor.setFont(font)

    def _applyEditorStyle(self) -> None:
        """Apply transparent styling and element-matched text color to the editor."""
        if self._editor is None or self._item is None:
            return

        # Apply stylesheet for transparent background with subtle border
        self._editor.setStyleSheet("""
            QPlainTextEdit {
                background: transparent;
                border: 1px solid rgba(255, 255, 255, 0.35);
                border-radius: 4px;
                padding: 2px;
                selection-background-color: rgba(0, 160, 255, 0.45);
                selection-color: white;
            }
        """)

        # Determine text color from element or default to black
        # Text elements currently render in black; check for future color property
        elem = self._item.elem
        text_color_str = getattr(elem, "text_color", None) or getattr(elem, "color", None)

        if text_color_str:
            base_color = QtGui.QColor(text_color_str)
            if not base_color.isValid():
                base_color = QtGui.QColor(QtCore.Qt.black)
        else:
            # Default: black text (matches how _paint_text renders)
            base_color = QtGui.QColor(QtCore.Qt.black)

        # Get dark mode state from view (or fallback to settings)
        dark_mode = getattr(self._view, "_dark_mode", False)

        # Compute display color for contrast in dark mode
        display_color = compute_display_color(base_color, dark_mode)

        # Apply text color via palette (doesn't conflict with stylesheet)
        pal = self._editor.palette()
        pal.setColor(QtGui.QPalette.Text, display_color)
        pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(QtCore.Qt.white))
        self._editor.setPalette(pal)

    def _updateGeometry(self) -> None:
        """Update the editor's position and size to match the item."""
        if self._editor is None or self._item is None:
            return

        # Get the item's scene bounding rect
        scene_rect = self._item.sceneBoundingRect()

        # Map entire scene rect to viewport coordinates
        # mapFromScene(QRectF) returns QPolygon; use boundingRect() for robust mapping
        # This avoids rounding drift from mapping individual corners at odd zoom levels
        view_polygon = self._view.mapFromScene(scene_rect)
        view_rect = view_polygon.boundingRect().normalized()

        # Enforce minimum size anchored to top-left corner
        min_width = 50
        min_height = 30
        if view_rect.width() < min_width:
            view_rect.setRight(view_rect.left() + min_width)
        if view_rect.height() < min_height:
            view_rect.setBottom(view_rect.top() + min_height)

        # Apply geometry to the editor widget
        self._editor.setGeometry(view_rect)

    def updateGeometry(self) -> None:
        """Public method to update editor geometry (call on zoom/pan)."""
        if self._is_editing:
            self._updateGeometry()

    def commitEdit(self) -> None:
        """Commit the current edit and close the editor."""
        if not self._is_editing or self._editor is None:
            return

        new_text = self._editor.toPlainText()
        self._finishEditing(new_text, commit=True)

    def cancelEdit(self) -> None:
        """Cancel the current edit and restore original text."""
        if not self._is_editing:
            return

        self._finishEditing(self._original_text, commit=False)

    def _onCommitted(self, new_text: str) -> None:
        """Handle committed signal from editor."""
        self._finishEditing(new_text, commit=True)

    def _onCancelled(self) -> None:
        """Handle cancelled signal from editor."""
        self._finishEditing(self._original_text, commit=False)

    def _finishEditing(self, final_text: str, commit: bool) -> None:
        """
        Finish editing and clean up.

        Args:
            final_text: The text to apply to the element
            commit: If True, create undo command; if False, just restore
        """
        if not self._is_editing:
            return

        item = self._item
        elem = item.elem if item else None

        # Re-enable item movement
        if item is not None:
            item.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, True)

        # Clean up editor widget
        if self._editor is not None:
            self._editor.committed.disconnect(self._onCommitted)
            self._editor.cancelled.disconnect(self._onCancelled)
            self._editor.hide()
            self._editor.deleteLater()
            self._editor = None

        # Apply text change
        if elem is not None and commit and final_text != self._original_text:
            # Create undo command
            self._createUndoCommand(elem, item, self._original_text, final_text)
        elif elem is not None and not commit:
            # Restore original text (no undo)
            elem.text = self._original_text
            if item is not None:
                item._cache_qimage = None
                item._cache_key = None
                item.update()

        # Reset state
        self._item = None
        self._original_text = ""
        self._is_editing = False

        # Return focus to the view
        self._view.setFocus()

    def _createUndoCommand(self, elem, item, old_text: str, new_text: str) -> None:
        """Create and push an undo command for the text change."""
        from ..core.commands import PropertyChangeCmd

        # Get undo stack from the main window
        main_window = self._getMainWindow()
        if main_window is None:
            # Fallback: just apply directly
            elem.text = new_text
            if item is not None:
                item._cache_qimage = None
                item._cache_key = None
                item.update()
            return

        undo_stack = getattr(main_window, "undo_stack", None)
        if undo_stack is None:
            # Fallback: just apply directly
            elem.text = new_text
            if item is not None:
                item._cache_qimage = None
                item._cache_key = None
                item.update()
            return

        # Create and push the command
        cmd = PropertyChangeCmd(
            elem,
            "text",
            old_text,
            new_text,
            "Edit text",
            item
        )
        undo_stack.push(cmd)

        # Notify properties panel to refresh
        if hasattr(main_window, "_on_selection_changed"):
            main_window._on_selection_changed()

    def _getMainWindow(self):
        """Get the main window from the view."""
        if self._view is None:
            return None
        return self._view.window()
