from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets
import json
import os
import random
import urllib.request

# Split modules
from ..core.models import Element, Template
from ..core.commands import AddItemCmd, DeleteItemCmd, MoveResizeCmd, PropertyChangeCmd, GroupItemsCmd, UngroupItemsCmd  # ready for future use
from ..core.render import scene_to_image
from ..core.barcodes import render_barcode_to_qimage, ean13_checksum, upca_checksum  # not strictly used yet
from ..printing.worker import PrinterWorker
from ..printing.profiles import PrinterProfile, load_profiles, save_profiles
from .items import (
    GItem,
    GLineItem,
    GRectItem,
    GEllipseItem,
    GStarItem,
    GuideLineItem,
    GArrowItem,
    GuideGridItem,
    GDiamondItem,
    create_item_from_element,
    SERIALIZABLE_ITEM_TYPES,
)
from .layers import LayerList
from .views import RulerView, PX_PER_MM
from .common import px_per_mm_factor, unpack_margins_mm
from .toolbox import Toolbox
from .properties import PropertiesPanel
from .variables import VariablePanel
from .inline_editor import CanvasTextEditorOverlay
from .actions import build_toolbars_and_menus
from .docks import build_docks, update_view_menu
from .canvas.controller import build_scene_view, setup_inline_editor, update_paper as _update_paper
from .dialogs import (
    PrintPreviewDialog,
    show_keyboard_shortcuts_dialog,
    show_duplicate_offset_dialog,
    show_printer_config_dialog,
    show_column_guides_dialog,
)
from . import persistence as _persist
from . import presets as _presets
from . import layout_ops as _layout


# -------------------------
# App constants / QSettings
# -------------------------
ORG_NAME = "ByteSized Labs"
APP_NAME = "Receipt Lab"
APP_VERSION = "0.9.5"

# Debug flag for autosave/recovery troubleshooting (set to True for debugging)
DEBUG_AUTOSAVE = False
# Debug flag for column-guide creation (set to True for debugging)
DEBUG_COLUMN_GUIDES = False
# Debug flag for print/export pipeline (set to True for debugging)
DEBUG_PRINTING = False

QtCore.QCoreApplication.setOrganizationName(ORG_NAME)
QtCore.QCoreApplication.setApplicationName(APP_NAME)
QtCore.QCoreApplication.setApplicationVersion(APP_VERSION)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"{APP_NAME} — {APP_VERSION}")
        self.resize(1300, 900)
        self.settings = QtCore.QSettings()

        self.template = Template()
        self._load_printer_profiles()

        self.threadpool = QtCore.QThreadPool.globalInstance()
        self.undo_stack = QtGui.QUndoStack(self)
        self.undo_stack.indexChanged.connect(self._on_undo_redo_changed)
        self._workers: set[PrinterWorker] = set()
        self._column_guides: list[GuideLineItem] = []
        self._alignment_guides: list[QtWidgets.QGraphicsLineItem] = []
        self._alignment_guide_pen = QtGui.QPen(QtGui.QColor(255, 0, 255), 1, QtCore.Qt.DashLine)
        self._last_duplicate_offset = QtCore.QPointF(10, 10)  # Default 10px offset
        self._snap_guard = False

        # Layer refresh re-entrancy guard
        self._layer_refreshing = False

        self._current_file_path: str | None = None
        self._has_unsaved_changes = False
        self._auto_save_timer = QtCore.QTimer(self)
        self._auto_save_timer.timeout.connect(self._auto_save)
        self._auto_save_timer.start(60000)  # 60 seconds
        

        self._build_scene_view()
        self._setup_inline_editor()
        self._build_toolbars_menus()
        self._build_docks()
        self._update_view_menu()
        self.scene.column_guide_positions = []

        self.update_paper()
        self._load_crash_recovery()
        self.apply_theme()
        self.statusBar().showMessage("Ready. Loaded saved printer settings.")

    # -------------------------
    # UI construction
    # -------------------------
    def _build_scene_view(self):
        build_scene_view(self)

    def _setup_inline_editor(self):
        setup_inline_editor(self)

    def _build_toolbars_menus(self):
        build_toolbars_and_menus(self)

    def _build_docks(self):
        build_docks(self)

    def _update_view_menu(self):
        update_view_menu(self)

    # -------------------------
    # Theme & paper
    # -------------------------
    def apply_theme(self):
        """Apply light or dark theme based on saved preference."""
        is_dark = self.settings.value("ui/dark_mode", False, type=bool)
        self._apply_theme_mode(is_dark)

    def _apply_theme_mode(self, dark: bool):
        """Apply the specified theme mode (True=dark, False=light)."""
        app = QtWidgets.QApplication.instance()
        if app is None:
            return

        if dark:
            # Dark palette
            palette = QtGui.QPalette()
            dark_color = QtGui.QColor(45, 45, 45)
            darker_color = QtGui.QColor(35, 35, 35)
            text_color = QtGui.QColor(220, 220, 220)
            disabled_color = QtGui.QColor(127, 127, 127)
            highlight_color = QtGui.QColor(42, 130, 218)
            link_color = QtGui.QColor(42, 130, 218)

            palette.setColor(QtGui.QPalette.Window, dark_color)
            palette.setColor(QtGui.QPalette.WindowText, text_color)
            palette.setColor(QtGui.QPalette.Base, darker_color)
            palette.setColor(QtGui.QPalette.AlternateBase, dark_color)
            palette.setColor(QtGui.QPalette.ToolTipBase, dark_color)
            palette.setColor(QtGui.QPalette.ToolTipText, text_color)
            palette.setColor(QtGui.QPalette.Text, text_color)
            palette.setColor(QtGui.QPalette.Button, dark_color)
            palette.setColor(QtGui.QPalette.ButtonText, text_color)
            palette.setColor(QtGui.QPalette.BrightText, QtCore.Qt.red)
            palette.setColor(QtGui.QPalette.Link, link_color)
            palette.setColor(QtGui.QPalette.Highlight, highlight_color)
            palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)

            # Disabled state
            palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, disabled_color)
            palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, disabled_color)
            palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, disabled_color)

            app.setPalette(palette)
            # Minimal stylesheet for elements QPalette doesn't fully cover
            app.setStyleSheet("""
                QToolTip { color: #dcdcdc; background-color: #2d2d2d; border: 1px solid #555555; }
            """)

            # Update canvas background for dark mode
            if hasattr(self, 'view'):
                self.view.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#1e1e1e")))
                if hasattr(self.view, 'setDarkMode'):
                    self.view.setDarkMode(True)
        else:
            # Light mode - restore default palette
            app.setPalette(app.style().standardPalette())
            app.setStyleSheet("")

            # Update canvas background for light mode
            if hasattr(self, 'view'):
                self.view.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
                if hasattr(self.view, 'setDarkMode'):
                    self.view.setDarkMode(False)

        # Force repaint
        if hasattr(self, 'view'):
            self.view.viewport().update()

    def _toggle_dark_mode(self, checked: bool):
        """Toggle dark mode on/off and persist the setting."""
        self.settings.setValue("ui/dark_mode", checked)
        self._apply_theme_mode(checked)
        mode_name = "Dark" if checked else "Light"
        self.statusBar().showMessage(f"{mode_name} mode enabled", 2000)

    def update_paper(self):
        _update_paper(self)

    # -------------------------
    # Actions
    # -------------------------
    def _on_toggle_margins(self, checked: bool):
        if hasattr(self.view, "setShowMargins"):
            self.view.setShowMargins(checked)
        else:
            setattr(self.view, "show_margins", bool(checked))
            self.view.viewport().update()

    # -------------------------
    # Insertion helpers
    # -------------------------
    def _default_insert_pos(self) -> QtCore.QPointF:
        """
        Returns a reasonable default position for newly inserted items:
        inside the top-left printable area (margins) with a bit of padding.
        """
        scene_rect = self.scene.sceneRect()
        page_w = scene_rect.width()
        page_h = scene_rect.height()

        ml, mt, mr, mb = unpack_margins_mm(self.scene)
        factor = px_per_mm_factor()

        # base position = top-left margin in px
        x = ml * factor
        y = mt * factor

        # add a tiny padding inside the margin so it's not jammed to the edge
        PAD_PX = 4.0
        x += PAD_PX
        y += PAD_PX

        # clamp to page (just in case margins are weird)
        x = max(0.0, min(x, page_w - 10.0))
        y = max(0.0, min(y, page_h - 10.0))

        return QtCore.QPointF(x, y)

    # -------------------------
    # Add items
    # -------------------------
    def add_text(self):
        pos = self._default_insert_pos()

        e = Element(
            kind="text",
            x=float(pos.x()),
            y=float(pos.y()),
            w=160.0,
            h=40.0,
            text="New Text",
        )
        item = GItem(e)
        item.undo_stack = self.undo_stack

        cmd = AddItemCmd(self.scene, item, text="Add text")
        self.undo_stack.push(cmd)
        item._main_window = self

        item.setPos(e.x, e.y)
        item.setSelected(True)
        self._refresh_layers_safe()

    def add_line(self):
        scene_rect = self.scene.sceneRect()
        page_w = scene_rect.width()

        ml, mt, mr, mb = unpack_margins_mm(self.scene)
        factor = px_per_mm_factor()

        PAD_PX = 4.0

        # X positions respect left/right margins, with a small padding
        x1 = ml * factor + PAD_PX
        x2 = page_w - (mr * factor) - PAD_PX

        # Y position: just inside the top margin, plus a little visual offset
        y = mt * factor + PAD_PX + 6.0

        p1 = QtCore.QPointF(x1, y)
        p2 = QtCore.QPointF(x2, y)

        item = GLineItem(p1, p2)
        item.undo_stack = self.undo_stack

        cmd = AddItemCmd(self.scene, item, text="Add line")
        self.undo_stack.push(cmd)

        item.setSelected(True)
        self._refresh_layers_safe()

    def add_rect(self):
        pos = self._default_insert_pos()
        rect = QtCore.QRectF(0.0, 0.0, 60.0, 30.0)

        item = GRectItem(rect)
        item.undo_stack = self.undo_stack
        item.setPos(pos)

        cmd = AddItemCmd(self.scene, item, text="Add rectangle")
        self.undo_stack.push(cmd)

        item.setSelected(True)
        self._refresh_layers_safe()

    def add_circle(self):
        """
        Circle tool: uses GEllipseItem with equal width/height.
        """
        pos = self._default_insert_pos()
        rect = QtCore.QRectF(0.0, 0.0, 40.0, 40.0)

        item = GEllipseItem(rect)
        item.undo_stack = self.undo_stack
        item.setPos(pos)

        cmd = AddItemCmd(self.scene, item, text="Add circle")
        self.undo_stack.push(cmd)

        item.setSelected(True)
        self._refresh_layers_safe()

    def add_star(self):
        pos = self._default_insert_pos()
        rect = QtCore.QRectF(0.0, 0.0, 50.0, 50.0)

        item = GStarItem(rect)
        item.undo_stack = self.undo_stack
        item.setPos(pos)

        cmd = AddItemCmd(self.scene, item, text="Add star")
        self.undo_stack.push(cmd)

        item.setSelected(True)
        self._refresh_layers_safe()

    def add_arrow(self):
        """
        Create a GArrowItem inside the top-left margin area.
        """
        ml, mt, mr, mb = unpack_margins_mm(self.template)
        factor = px_per_mm_factor()

        base_x = ml * factor + 10.0
        base_y = mt * factor + 10.0

        p1 = QtCore.QPointF(base_x, base_y)
        p2 = QtCore.QPointF(base_x + 60.0, base_y)

        item = GArrowItem(p1, p2)
        item.undo_stack = self.undo_stack

        cmd = AddItemCmd(self.scene, item, text="Add arrow")
        self.undo_stack.push(cmd)

        item.setSelected(True)
        self._refresh_layers_safe()

    def add_diamond(self):
        """
        Add a diamond shape (rect-based, drawn as a rotated square).
        """
        pos = self._default_insert_pos()
        rect = QtCore.QRectF(0.0, 0.0, 40.0, 40.0)

        from .items import GDiamondItem

        item = GDiamondItem(rect)
        item.undo_stack = self.undo_stack
        item.setPos(pos)

        cmd = AddItemCmd(self.scene, item, text="Add diamond")
        self.undo_stack.push(cmd)

        item.setSelected(True)
        self._refresh_layers_safe()

    def add_image(self):
        """
        Add an image element (PNG/SVG).
        Stores absolute image path in elem.image_path and uses elem.text
        as a friendly label (basename).
        """
        # ========== Patch 9: File selection ==========
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.svg);;All files (*.*)",
        )
        if not path:
            return

        # ========== Patch 9: File validation with error handling ==========
        try:
            path = os.path.abspath(path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Path",
                f"Could not resolve image path:\n\n{e}"
            )
            return
        
        # Verify file exists and is readable
        if not os.path.exists(path):
            QtWidgets.QMessageBox.critical(
                self,
                "File Not Found",
                f"The image file could not be found:\n{path}"
            )
            return
        
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid File",
                f"The selected path is not a file:\n{path}"
            )
            return
        
        # Try to load the image to verify it's valid
        try:
            test_img = QtGui.QImage(path)
            if test_img.isNull():
                raise ValueError("Image failed to load - file may be corrupted or unsupported format")
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(
                self,
                "File Not Found",
                f"The image file could not be found:\n{path}"
            )
            return
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                self,
                "Permission Denied",
                f"You don't have permission to read this file:\n{path}"
            )
            return
        except ValueError as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Image",
                f"Could not load image:\n{path}\n\n{e}"
            )
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Image Load Error",
                f"An error occurred while loading the image:\n{path}\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            return

        # ========== Portable asset copy dialog ==========
        final_path = path  # Default: link to original
        if self._current_file_path:
            # Template is saved - offer to copy into assets/
            msg = QtWidgets.QMessageBox(self)
            msg.setWindowTitle("Add Image")
            msg.setText("Copy image into this template's folder for portability?")
            msg.setInformativeText(
                "Copying makes the template self-contained and easier to share."
            )
            btn_copy = msg.addButton("Copy to assets/ (recommended)", QtWidgets.QMessageBox.AcceptRole)
            btn_link = msg.addButton("Link to original file", QtWidgets.QMessageBox.RejectRole)
            btn_cancel = msg.addButton(QtWidgets.QMessageBox.Cancel)
            msg.setDefaultButton(btn_copy)
            msg.exec()

            clicked = msg.clickedButton()
            if clicked == btn_cancel:
                return  # User cancelled
            elif clicked == btn_copy:
                copied_path = self._copy_image_to_assets(path)
                if copied_path:
                    final_path = copied_path  # Use relative path to copied file
                # If copy failed, final_path stays as original absolute path
        else:
            # Template not saved yet - show gentle info message
            self.statusBar().showMessage(
                "Tip: Save the template to enable portable asset copying.", 5000
            )

        # ========== Patch 9: Element creation with error handling ==========
        try:
            # default geometry in px
            w_mm = 25.0
            h_mm = 15.0
            factor = px_per_mm_factor()

            w_px = w_mm * factor
            h_px = h_mm * factor
            x_px = 5.0 * factor
            y_px = 5.0 * factor

            elem = Element(
                kind="image",
                text=os.path.basename(path),  # nice label for Layers/Props
                x=float(x_px),
                y=float(y_px),
                w=float(w_px),
                h=float(h_px),
            )
            elem.image_path = final_path

            item = GItem(elem)
            item.undo_stack = self.undo_stack
            item._main_window = self
            item.setPos(x_px, y_px)

            cmd = AddItemCmd(self.scene, item, text="Add image")
            self.undo_stack.push(cmd)

            # select it
            self.scene.clearSelection()
            item.setSelected(True)

            # keep UI in sync
            self._refresh_layers_safe()
            self._on_selection_changed()
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Image Creation Error",
                f"Could not create image element:\n\n"
                f"Error: {type(e).__name__}: {e}"
            )


    def _default_inset_xy(self, w_px: float = 160.0, h_px: float = 40.0) -> tuple[float, float]:
        """
        Pick a default position slightly inside the printable margins so
        new items aren't glued to the very edge.
        """
        scene_rect = self.scene.sceneRect()
        ml, mt, mr, mb = unpack_margins_mm(self.scene)
        factor = px_per_mm_factor()

        x = ml * factor + 10.0
        y = mt * factor + 10.0

        # Keep within scene bounds
        if scene_rect.width() >= w_px:
            x = min(max(x, scene_rect.left()), scene_rect.right() - w_px)
        else:
            x = scene_rect.left()

        if scene_rect.height() >= h_px:
            y = min(max(y, scene_rect.top()), scene_rect.bottom() - h_px)
        else:
            y = scene_rect.top()

        return x, y

    def add_barcode(self):
        """
        Insert a new barcode element (Phase 1: Code128 by default).
        """
        # Reasonable default size for a receipt barcode
        w_px = 200.0
        h_px = 60.0
        x, y = self._default_inset_xy(w_px, h_px)

        e = Element(
            kind="barcode",
            x=x,
            y=y,
            w=w_px,
            h=h_px,
            text="123456789012",  # default sample data
        )
        e.bc_type = "Code128"  # renderer hint

        item = GItem(e)
        item.undo_stack = self.undo_stack
        item._main_window = self

        cmd = AddItemCmd(self.scene, item, text="Add barcode")
        self.undo_stack.push(cmd)

        item.setPos(e.x, e.y)
        item.setSelected(True)
        self._refresh_layers_safe()

    # -------------------------
    # Printing & export
    # -------------------------
    def print_now(self):
        """
        Render the current scene to a QImage and send it to the printer worker.
        """
        # Check for missing variables (non-blocking warning)
        self._warn_missing_variables()

        # ========== Patch 9: Render with error handling ==========
        try:
            img = scene_to_image(self.scene, scale=1.0)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Render Error",
                f"Could not render the scene to an image:\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            if DEBUG_PRINTING:
                print(f"[PRINT DEBUG] Render exception: {e}")
            return

        if img is None or img.isNull():
            QtWidgets.QMessageBox.warning(
                self, "Print Error", "Could not render the scene to an image."
            )
            if DEBUG_PRINTING:
                print("[PRINT DEBUG] scene_to_image returned null image")
            return

        if DEBUG_PRINTING:
            print(
                "[PRINT DEBUG] scene_to_image returned:",
                img.width(),
                "x",
                img.height(),
            )

        # ========== Patch 9: Printer worker with error handling ==========
        try:
            worker = PrinterWorker(
                action="print",
                payload={
                    "image": img,
                    "config": self.printer_cfg,
                },
            )
            self._workers.add(worker)

            def _on_finished():
                self.statusBar().showMessage("Print job finished", 3000)
                try:
                    self._workers.discard(worker)
                except Exception:
                    pass

            def _on_error(err: str):
                if DEBUG_PRINTING:
                    print("[PRINT ERROR]", err)
                self.statusBar().showMessage(f"Print error: {err}", 5000)
                QtWidgets.QMessageBox.critical(
                    self,
                    "Print Error",
                    f"The printer reported an error:\n\n{err}\n\n"
                    "Please check:\n"
                    "• Printer is powered on and connected\n"
                    "• Printer has paper loaded\n"
                    "• No paper jams or other issues"
                )

            worker.signals.finished.connect(_on_finished)
            worker.signals.error.connect(_on_error)
            worker.start()
            
        except ConnectionError:
            QtWidgets.QMessageBox.critical(
                self,
                "Printer Connection Error",
                "Could not connect to the printer. Please check:\n\n"
                "• Printer is powered on\n"
                "• USB/Network cable is connected\n"
                "• Printer drivers are installed\n"
                "• No other application is using the printer"
            )
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                self,
                "Printer Permission Error",
                "You don't have permission to access the printer.\n\n"
                "Try running the application as administrator or check printer permissions."
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Print Error",
                f"An error occurred while starting the print job:\n\n"
                f"Error: {type(e).__name__}: {e}"
            )

    def export_png(self):
        """
        Render the current scene to a PNG image file.
        """
        # ========== Patch 9: Render with error handling ==========
        try:
            img = scene_to_image(self.scene, scale=1.0)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Render Error",
                f"Could not render the scene to an image:\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            return

        if img is None or img.isNull():
            QtWidgets.QMessageBox.warning(
                self, "Export Error", "Could not render the scene to an image."
            )
            return

        # ========== Patch 9: File dialog ==========
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export as PNG", "", "PNG Images (*.png)"
        )
        if not path:
            return

        # Ensure .png extension
        if not path.lower().endswith('.png'):
            path += '.png'

        # ========== Patch 9: Save with error handling ==========
        try:
            ok = img.save(path, "PNG")
            if not ok:
                raise IOError("QImage.save() returned False - save operation failed")
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                self,
                "Permission Denied",
                f"You don't have permission to write to:\n{path}\n\n"
                "Try saving to a different location."
            )
            return
        except OSError as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Export Error",
                f"Could not save PNG file:\n{path}\n\n"
                f"Error: {e}\n\n"
                "Check that you have enough disk space."
            )
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Unexpected Error",
                f"An unexpected error occurred during export:\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            return

        self.statusBar().showMessage(f"Exported PNG: {path}", 3000)

    def export_pdf(self):
        """
        Render the current scene to a single-page PDF file.
        """
        # ========== Patch 9: Render with error handling ==========
        try:
            img = scene_to_image(self.scene, scale=1.0)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Render Error",
                f"Could not render the scene to an image:\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            return

        if img is None or img.isNull():
            QtWidgets.QMessageBox.warning(
                self, "Export Error", "Could not render the scene to an image."
            )
            return

        # ========== Patch 9: File dialog ==========
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export as PDF", "", "PDF Files (*.pdf)"
        )
        if not path:
            return

        # Ensure .pdf extension
        if not path.lower().endswith('.pdf'):
            path += '.pdf'

        # ========== Patch 9: PDF creation with error handling ==========
        try:
            writer = QtGui.QPdfWriter(path)
            try:
                writer.setResolution(self.template.dpi)
                writer.setPageSizeMM(
                    QtCore.QSizeF(self.template.width_mm, self.template.height_mm)
                )
            except AttributeError:
                # If template is missing attributes, use defaults
                writer.setResolution(203)
                writer.setPageSizeMM(QtCore.QSizeF(80, 200))
            except Exception as e:
                if DEBUG_PRINTING:
                    print(f"Warning: Could not set PDF page size: {e}")
                # Continue with Qt defaults

            painter = QtGui.QPainter(writer)
            if not painter.isActive():
                raise IOError("Could not begin painting to PDF - file may be locked or path invalid")

            page_rect = painter.viewport()
            img_size = img.size()
            img_size.scale(page_rect.size(), QtCore.Qt.KeepAspectRatio)
            painter.setViewport(
                page_rect.x(),
                page_rect.y(),
                img_size.width(),
                img_size.height(),
            )
            painter.setWindow(img.rect())
            painter.drawImage(0, 0, img)
            painter.end()

        except PermissionError:
            QtWidgets.QMessageBox.critical(
                self,
                "Permission Denied",
                f"You don't have permission to write to:\n{path}\n\n"
                "Try saving to a different location."
            )
            return
        except OSError as e:
            QtWidgets.QMessageBox.critical(
                self,
                "PDF Export Error",
                f"Could not create PDF file:\n{path}\n\n"
                f"Error: {e}\n\n"
                "Check that you have enough disk space and the path is valid."
            )
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Unexpected Error",
                f"An error occurred during PDF export:\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            return

        self.statusBar().showMessage(f"Exported PDF: {path}", 3000)

    def quick_action(self, action: str):
        """
        Fire a simple 'feed' or 'cut' action via the printer worker.
        """
        worker = PrinterWorker(
            action=action,
            payload={"config": self.printer_cfg},
        )
        self._workers.add(worker)

        def _on_finished():
            self.statusBar().showMessage(f"{action.title()} done", 2000)
            try:
                self._workers.discard(worker)
            except Exception:
                pass

        def _on_error(err: str):
            if DEBUG_PRINTING:
                print(f"[PRINT ERROR:{action}]", err)
            self.statusBar().showMessage(f"{action.title()} error: {err}", 5000)
            QtWidgets.QMessageBox.warning(self, f"{action.title()} error", err)

        worker.signals.finished.connect(_on_finished)
        worker.signals.error.connect(_on_error)
        worker.start()

    # -------------------------
    # Persistence (Template + Printer)
    # -------------------------
    def save_template(self):
        """Save template to file with improved error handling."""
        _persist.save_template(self)

    def load_template(self):
        """Load template from file with improved error handling."""
        _persist.load_template(self)

    def _mark_unsaved(self):
        """Mark that changes have been made (called when scene changes)."""
        _persist.mark_unsaved(self)

    def _auto_save(self):
        """Auto-save current template to temp location every 60 seconds."""
        _persist.auto_save(self)

    def _load_crash_recovery(self):
        """Check for auto-saved file on startup and offer to restore."""
        _persist.load_crash_recovery(self)

    def _delete_autosave_file(self):
        """Delete the autosave file if it exists."""
        _persist.delete_autosave_file(self)

    # ------------ Persistence thin wrappers (see ui/persistence.py) ------------

    def _normalize_path(self, path: str) -> str:
        """Normalize a file path for consistent comparison."""
        return _persist.normalize_path(path)

    def _dedupe_recent_files(self, paths: list) -> list:
        """Remove duplicate paths from recent files list."""
        return _persist.dedupe_recent_files(paths)

    def _remove_from_recent_by_normalized(self, path_to_remove: str) -> None:
        """Remove a path from recent files, matching by normalized path."""
        _persist.remove_from_recent_by_normalized(self, path_to_remove)

    def _make_asset_path_portable(self, asset_path: str, template_path: str) -> str:
        """Convert an absolute asset path to relative if inside template dir."""
        return _persist.make_asset_path_portable(asset_path, template_path)

    def _resolve_asset_path(self, asset_path: str, template_path: str) -> str:
        """Resolve relative asset path to absolute based on template location."""
        return _persist.resolve_asset_path(asset_path, template_path)

    def _make_elements_portable(self, elements: list, template_path: str) -> list:
        """Make asset paths in element dicts portable (relative)."""
        return _persist.make_elements_portable(elements, template_path)

    def _resolve_element_paths(self, elements: list, template_path: str) -> list:
        """Resolve relative asset paths in element dicts to absolute."""
        return _persist.resolve_element_paths(elements, template_path)

    def _copy_image_to_assets(self, source_path: str) -> str | None:
        """Copy an image file into the template's assets/ folder."""
        return _persist.copy_image_to_assets(self, source_path)

    def _refresh_recent_menu(self):
        """Refresh the Recent Files menu from settings."""
        _persist.refresh_recent_menu(self)

    def _update_recent_files(self, path: str):
        """Add a file to the recent files list."""
        _persist.update_recent_files(self, path)

    def _load_template_path(self, path: str):
        """Load template from a specific file path."""
        _persist.load_template_path(self, path)

    def _clear_recent_files(self):
        """Clear the recent files list with confirmation."""
        _persist.clear_recent_files(self)

    def preview_print(self):
        """Show print preview dialog before printing"""
        # Check for missing variables (non-blocking warning)
        self._warn_missing_variables()

        img = scene_to_image(self.scene, scale=1.0)
        
        if img is None or img.isNull():
            QtWidgets.QMessageBox.warning(
                self,
                "Preview Error",
                "Could not render scene for preview"
            )
            return
        
        dlg = PrintPreviewDialog(img, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            # User clicked "Print" in the preview dialog
            self.print_now()

    def _show_alignment_guides(self, moving_item: GItem):
        """Show alignment guides when item aligns with others"""
        self._clear_alignment_guides()
        
        if not moving_item:
            return
        
        ALIGN_THRESHOLD = 3.0  # pixels
        moving_rect = moving_item.sceneBoundingRect()
        
        # Get all other items (excluding guides, grid, and the moving item)
        other_items = [
            item for item in self.scene.items()
            if isinstance(item, GItem) and item != moving_item
            and not isinstance(item, (GuideLineItem, GuideGridItem))
        ]
        
        if not other_items:
            return
        
        # Check for alignment on each edge and center
        moving_left = moving_rect.left()
        moving_right = moving_rect.right()
        moving_hcenter = moving_rect.center().x()
        moving_top = moving_rect.top()
        moving_bottom = moving_rect.bottom()
        moving_vcenter = moving_rect.center().y()
        
        scene_height = self.template.height_px
        scene_width = self.template.width_px
        
        for other in other_items:
            other_rect = other.sceneBoundingRect()
            
            # Horizontal alignment checks
            # Left edges align
            if abs(moving_left - other_rect.left()) < ALIGN_THRESHOLD:
                line = self.scene.addLine(
                    moving_left, 0, moving_left, scene_height,
                    self._alignment_guide_pen
                )
                self._alignment_guides.append(line)
            
            # Right edges align
            if abs(moving_right - other_rect.right()) < ALIGN_THRESHOLD:
                line = self.scene.addLine(
                    moving_right, 0, moving_right, scene_height,
                    self._alignment_guide_pen
                )
                self._alignment_guides.append(line)
            
            # Horizontal centers align
            if abs(moving_hcenter - other_rect.center().x()) < ALIGN_THRESHOLD:
                line = self.scene.addLine(
                    moving_hcenter, 0, moving_hcenter, scene_height,
                    self._alignment_guide_pen
                )
                self._alignment_guides.append(line)
            
            # Vertical alignment checks
            # Top edges align
            if abs(moving_top - other_rect.top()) < ALIGN_THRESHOLD:
                line = self.scene.addLine(
                    0, moving_top, scene_width, moving_top,
                    self._alignment_guide_pen
                )
                self._alignment_guides.append(line)
            
            # Bottom edges align
            if abs(moving_bottom - other_rect.bottom()) < ALIGN_THRESHOLD:
                line = self.scene.addLine(
                    0, moving_bottom, scene_width, moving_bottom,
                    self._alignment_guide_pen
                )
                self._alignment_guides.append(line)
            
            # Vertical centers align
            if abs(moving_vcenter - other_rect.center().y()) < ALIGN_THRESHOLD:
                line = self.scene.addLine(
                    0, moving_vcenter, scene_width, moving_vcenter,
                    self._alignment_guide_pen
                )
                self._alignment_guides.append(line)

    def _clear_alignment_guides(self):
        """Remove all alignment guides"""
        for guide in self._alignment_guides:
            self.scene.removeItem(guide)
        self._alignment_guides.clear()

    # -------------------------
    # Fortune helper
    # -------------------------
    def _get_random_fortune(self) -> tuple[str, str]:
        """Fetch a random fortune (text, lucky_numbers)."""
        return _presets.get_random_fortune()

    def _maybe_refresh_fortune_cookie(self) -> bool:
        """Refresh fortune-cookie text in-place if layout exists."""
        return _presets.maybe_refresh_fortune_cookie(self)

    def load_printer_settings(self) -> dict:
        s = self.settings
        return {
            "interface": s.value("printer/interface", "network"),
            "host": s.value("printer/host", "192.168.1.50"),
            "port": int(s.value("printer/port", 9100)),
            "darkness": int(s.value("printer/darkness", 200)),
            "threshold": int(s.value("printer/threshold", 180)),
            "cut_mode": (s.value("printer/cut_mode", "partial") or "partial"),
            "dpi": int(s.value("printer/dpi", 203)),
            "width_px": int(s.value("printer/width_px", 0)),
            "timeout": float(s.value("printer/timeout", 30.0)),
            "profile": s.value("printer/profile", "TM-T88IV"),
        }

    def save_printer_settings(self):
        s = self.settings
        cfg = self.printer_cfg

        # Legacy single-config keys (keep for backwards compatibility)
        s.setValue("printer/interface", cfg.get("interface", "network"))
        s.setValue("printer/host", cfg.get("host", "192.168.1.50"))
        s.setValue("printer/port", int(cfg.get("port", 9100)))
        s.setValue("printer/darkness", int(cfg.get("darkness", 200)))
        s.setValue("printer/threshold", int(cfg.get("threshold", 180)))
        s.setValue("printer/cut_mode", cfg.get("cut_mode", "partial"))
        s.setValue("printer/dpi", int(cfg.get("dpi", 203)))
        s.setValue("printer/width_px", int(cfg.get("width_px", 0)))
        s.setValue("printer/timeout", float(cfg.get("timeout", 30.0)))
        s.setValue("printer/profile", cfg.get("profile", "TM-T88IV"))

        # Update current profile config and persist the profiles JSON
        if hasattr(self, "profiles") and hasattr(self, "current_profile_index"):
            if 0 <= self.current_profile_index < len(self.profiles):
                self.profiles[self.current_profile_index]["config"] = dict(cfg)
                self._save_printer_profiles()

    def _load_printer_profiles(self) -> None:
        """
        Load printer profiles from QSettings via printing.profiles module.

        If no profiles JSON is present, migrate from the legacy single
        printer config (load_printer_settings) into a 'Default' profile.
        """
        # Use the centralized profiles module (single source of truth)
        profile_objs = load_profiles(load_single_fn=self.load_printer_settings)

        # Convert to list[dict] for internal use (maintains compatibility)
        self.profiles: list[dict] = [p.to_dict() for p in profile_objs]

        # Restore active profile by name (persisted across restarts)
        self.current_profile_index: int = self._restore_active_profile_index()

        # Active config is a copy so we can tweak it in-memory
        if self.profiles:
            self.printer_cfg: dict = dict(self.profiles[self.current_profile_index]["config"])
        else:
            self.printer_cfg: dict = {}

    def _save_printer_profiles(self) -> None:
        """
        Persist all printer profiles to QSettings via printing.profiles module.
        """
        if not hasattr(self, "profiles"):
            return

        try:
            # Convert list[dict] to list[PrinterProfile] for the module
            profile_objs = [PrinterProfile.from_dict(p) for p in self.profiles]
            save_profiles(profile_objs)
        except Exception:
            # Don't crash the app just because save failed
            pass

    def _restore_active_profile_index(self) -> int:
        """
        Restore the active profile index by name from QSettings.

        Returns the index of the previously selected profile, or 0 if not found.
        If the saved profile name no longer exists (renamed/deleted), falls back
        to the first profile and updates the saved key.
        """
        if not self.profiles:
            return 0

        saved_name = self.settings.value("printer/active_profile_name", "", type=str)

        # Search for a profile with the saved name
        for idx, profile in enumerate(self.profiles):
            if profile.get("name", "") == saved_name:
                return idx

        # Fallback: saved profile not found, use first profile and update the key
        fallback_name = self.profiles[0].get("name", "")
        self.settings.setValue("printer/active_profile_name", fallback_name)
        return 0

    def _refresh_profile_combo(self) -> None:
        """
        Refresh the profile combo box from self.profiles and
        dynamically size it based on the longest profile name.
        """
        if not hasattr(self, "profile_combo"):
            return

        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()

        current_name = ""
        longest_name = ""

        if hasattr(self, "profiles"):
            for p in self.profiles:
                name = p.get("name", "Unnamed")
                idx = self.profile_combo.count()
                self.profile_combo.addItem(name)
                # full name as tooltip for that item
                self.profile_combo.setItemData(idx, name, QtCore.Qt.ToolTipRole)

                if len(name) > len(longest_name):
                    longest_name = name

        if (
            hasattr(self, "current_profile_index")
            and 0 <= self.current_profile_index < self.profile_combo.count()
        ):
            self.profile_combo.setCurrentIndex(self.current_profile_index)
            try:
                current_name = self.profiles[self.current_profile_index].get("name", "")
            except Exception:
                current_name = ""

        # widget-level tooltip shows current profile’s full name
        self.profile_combo.setToolTip(current_name or "Printer profile")

        # Dynamically size width based on longest profile name
        if longest_name:
            fm = self.profile_combo.fontMetrics()
            text_width = fm.horizontalAdvance(longest_name)

            # Some extra padding for icon/arrow and margins
            style = self.profile_combo.style()
            frame_w = style.pixelMetric(QtWidgets.QStyle.PM_ComboBoxFrameWidth)
            padding = frame_w * 6  # bump this if still too tight

            # Cap it so it doesn't eat the whole toolbar
            min_width = min(text_width + padding, 320)
            self.profile_combo.setMinimumWidth(min_width)

        self.profile_combo.blockSignals(False)

    def _on_profile_changed(self, idx: int) -> None:
        """
        Switch active printer config when the user picks another profile.
        """
        if not hasattr(self, "profiles"):
            return
        if idx < 0 or idx >= len(self.profiles):
            return

        self.current_profile_index = idx
        self.printer_cfg = dict(self.profiles[idx].get("config") or {})

        # Update combo tooltip with full name
        name = self.profiles[idx].get("name", "")
        if hasattr(self, "profile_combo"):
            self.profile_combo.setToolTip(name or "Printer profile")

        # Persist active profile name for restore on next startup
        self.settings.setValue("printer/active_profile_name", name)

        # Update darkness spinbox
        if hasattr(self, "sb_darkness"):
            self.sb_darkness.blockSignals(True)
            self.sb_darkness.setValue(int(self.printer_cfg.get("darkness", 200)))
            self.sb_darkness.blockSignals(False)

        # Update cut combo
        if hasattr(self, "cb_cut"):
            saved_cut = (self.printer_cfg.get("cut_mode", "partial") or "partial").lower()
            _cut_map = {"full": "Full", "partial": "Partial", "none": "None"}
            self.cb_cut.blockSignals(True)
            self.cb_cut.setCurrentText(_cut_map.get(saved_cut, "Partial"))
            self.cb_cut.blockSignals(False)

        # Persist settings (also updates legacy single-printer keys)
        self.save_printer_settings()

    def configure_printer(self):
        result = show_printer_config_dialog(self.printer_cfg, parent=self)
        if result is not None:
            self.printer_cfg.update(result)
            self.save_printer_settings()

    # -------------------------
    # Keyboard handling via eventFilter
    # -------------------------
    def eventFilter(self, obj, event):
        # ========== NEW: Patch 7 - Live Alignment Guides ==========
        # Handle mouse events for alignment guide display
        if obj in (self.view, self.view.viewport()):
            # Mouse move during drag - show alignment guides
            if event.type() == QtCore.QEvent.MouseMove:
                # Check if we're dragging items
                if event.buttons() & QtCore.Qt.LeftButton:
                    items = self.scene.selectedItems()
                    if len(items) == 1 and isinstance(items[0], GItem):
                        self._show_alignment_guides(items[0])
            
            # Mouse release - clear alignment guides
            elif event.type() == QtCore.QEvent.MouseButtonRelease:
                if event.button() == QtCore.Qt.LeftButton:
                    self._clear_alignment_guides()
        # ========== END NEW ==========
        
        # Existing keyboard handling
        if (
            event.type() == QtCore.QEvent.KeyPress
            and obj in (self.view, self.view.viewport())
        ):
            key_event: QtGui.QKeyEvent = event
            key = key_event.key()
            mods = key_event.modifiers()

            ctrl = bool(mods & QtCore.Qt.ControlModifier)
            shift = bool(mods & QtCore.Qt.ShiftModifier)

            # Duplicate: Ctrl + D
            if ctrl and key == QtCore.Qt.Key_D:
                self._duplicate_selected_items()
                return True

            # Group / Ungroup: Ctrl+G / Ctrl+Shift+G
            if ctrl and key == QtCore.Qt.Key_G:
                if shift:
                    self._ungroup_selected()
                else:
                    self._group_selected()
                return True

            # Delete: Delete key
            if key == QtCore.Qt.Key_Delete:
                self._delete_selected_items()
                return True

            # Arrow-key nudging
            if key in (
                QtCore.Qt.Key_Left,
                QtCore.Qt.Key_Right,
                QtCore.Qt.Key_Up,
                QtCore.Qt.Key_Down,
            ):
                base_step_mm = 0.5
                big_step_mm = 2.0
                factor = px_per_mm_factor()

                step_mm = big_step_mm if shift else base_step_mm
                step_px = step_mm * factor

                dx = 0.0
                dy = 0.0
                if key == QtCore.Qt.Key_Left:
                    dx = -step_px
                elif key == QtCore.Qt.Key_Right:
                    dx = step_px
                elif key == QtCore.Qt.Key_Up:
                    dy = -step_px
                elif key == QtCore.Qt.Key_Down:
                    dy = step_px

                self._nudge_selected(dx, dy)
                return True

        return super().eventFilter(obj, event)

    def _nudge_selected(self, dx: float, dy: float):
        _layout.nudge_selected(self, dx, dy)

    def _duplicate_selected_items(self):
        """Duplicate selected items with remembered offset."""
        _layout.duplicate_selected_items(self)

    # -------------------------
    # Helpers & selection sync
    # -------------------------
    def _refresh_layers_safe(self) -> None:
        """
        Safely refresh the Layers dock without getting into recursive
        selectionChanged/changed loops.
        """
        if getattr(self, "_layer_refreshing", False):
            return

        self._layer_refreshing = True
        try:
            if hasattr(self, "layer_list") and self.layer_list is not None:
                self.layer_list.refresh()
        finally:
            self._layer_refreshing = False

    def _refresh_variable_panel(self) -> None:
        """Refresh the variable panel to reflect current template variables."""
        if hasattr(self, "variable_panel") and self.variable_panel is not None:
            self.variable_panel.refresh_all()

    def _warn_missing_variables(self) -> None:
        """Show non-blocking status bar warning if template uses undefined variables."""
        from .variables import scan_used_variables

        try:
            used = scan_used_variables(self.template)
            defined = set(self.template.variable_manager.get_all_variables().keys())
            missing = used - defined

            if missing:
                names = ", ".join(sorted(missing))
                self.statusBar().showMessage(
                    f"Warning: Undefined variables: {names}", 5000
                )
        except Exception:
            pass  # Don't block print/preview on error

    def _on_selection_changed(self) -> None:
        if not hasattr(self, "scene") or self.scene is None:
            return

        items = self.scene.selectedItems()

        # 🔑 single source of truth for properties
        if hasattr(self, "props"):
            try:
                self.props.set_target_from_selection(items)
            except Exception as e:
                if DEBUG_PRINTING:
                    print("[Properties] bind error:", e)

        # keep Layers in sync
        self._refresh_layers_safe()

    def _apply_snapping_to_selected(self):
        """Snapping now handled in GItem.itemChange (live during drag)."""
        return

    def _on_scene_changed(self, _region_list=None):
        """
        Scene changed: just keep properties panel in sync with model geometry.
        Snapping is now handled live in GItem.itemChange.
        """
        if not hasattr(self, "props") or self.props is None:
            return
        if hasattr(self.props, "refresh_geometry_from_model"):
            self.props.refresh_geometry_from_model()

        # Optional: keep Layers list refreshed on geometry changes
        if hasattr(self, "_refresh_layers_safe"):
            self._refresh_layers_safe()

        # Debounced refresh of used variables (picks up text edits)
        if hasattr(self, "variable_panel") and self.variable_panel is not None:
            self.variable_panel.schedule_refresh_used_vars()
    
    def _on_props_element_changed(self, *args) -> None:
        """
        Called when the Properties panel changes an element.

        - Repaints the scene so geometry/appearance updates.
        - Refreshes the Layers panel if available.
        """
        scene = getattr(self, "scene", None)
        if scene is not None:
            scene.update()  # <- actually call it

        # If you have a helper to refresh layers, call it too.
        if hasattr(self, "_refresh_layers_safe"):
            self._refresh_layers_safe()

    def _set_duplicate_offset_dialog(self):
        """Allow user to customize duplicate offset."""
        result = show_duplicate_offset_dialog(self._last_duplicate_offset, parent=self)
        if result is not None:
            self._last_duplicate_offset = result
            self.statusBar().showMessage(
                f"Duplicate offset set to ({result.x():.0f}, {result.y():.0f}) px",
                3000,
            )

    def _on_darkness_changed(self, val: int):
        self.printer_cfg["darkness"] = int(val)
        self.save_printer_settings()

    def _align_selected(self, mode: str):
        """Align selected items to page or margins."""
        _layout.align_selected(self, mode)

    def _distribute_selected(self, axis: str):
        """Distribute selected items evenly along axis."""
        _layout.distribute_selected(self, axis)

    def _group_selected(self):
        """Group selected items (undoable)."""
        _layout.group_selected(self)

    def _ungroup_selected(self):
        """Ungroup selected item groups (undoable)."""
        _layout.ungroup_selected(self)

    def _change_z_order(self, mode: str):
        """Change z-order of selected items."""
        _layout.change_z_order(self, mode)

    def _lock_selected(self):
        """Lock selected items."""
        _layout.lock_selected(self)

    def _unlock_selected(self):
        """Unlock selected items."""
        _layout.unlock_selected(self)

    def _set_column_guides_dialog(self):
        """Show dialog to set column guides with width options"""
        result = show_column_guides_dialog(parent=self)
        if result is None:
            return

        num_cols = result.num_cols
        mode = result.mode
        custom_width_mm = result.custom_width_mm

        self._clear_column_guides()

        # Get margins from margins_mm tuple (left, top, right, bottom)
        ml, mt, mr, mb = self.template.margins_mm

        if DEBUG_COLUMN_GUIDES:
            print(f"\n[DEBUG] Column Guides Creation")
            print(f"[DEBUG] Mode: {mode}")
            print(f"[DEBUG] Number of columns: {num_cols}")
            print(f"[DEBUG] Template width: {self.template.width_mm}mm")
            print(f"[DEBUG] Margins (L,T,R,B): {ml}, {mt}, {mr}, {mb} mm")
            print(f"[DEBUG] PX_PER_MM: {PX_PER_MM}")

        # Calculate column positions
        printable_width = self.template.width_mm - ml - mr
        start_x = ml * self.template.px_per_mm

        if DEBUG_COLUMN_GUIDES:
            print(f"[DEBUG] Printable width: {printable_width}mm")
            print(f"[DEBUG] Start X: {start_x}px")

        guide_positions = []

        if mode == "Equal width":
            # Equal width columns
            col_width = printable_width / num_cols

            if DEBUG_COLUMN_GUIDES:
                print(f"[DEBUG] Equal width mode - Column width: {col_width}mm")

            for i in range(num_cols + 1):
                x = start_x + (i * col_width * self.template.px_per_mm)
                guide = GuideLineItem(x, 0, x, self.template.height_px)
                self.scene.addItem(guide)
                self._column_guides.append(guide)
                guide_positions.append(x)

                if DEBUG_COLUMN_GUIDES:
                    print(f"[DEBUG] Guide {i}: x={x:.2f}px")
        else:
            # Custom width columns
            col_width_px = custom_width_mm * self.template.px_per_mm
            x = start_x
            guide_positions.append(x)

            if DEBUG_COLUMN_GUIDES:
                print(f"[DEBUG] Custom width mode - Column width: {custom_width_mm}mm ({col_width_px:.2f}px)")
                print(f"[DEBUG] Guide 0: x={x:.2f}px (left margin)")

            # First guide at left margin
            guide = GuideLineItem(x, 0, x, self.template.height_px)
            self.scene.addItem(guide)
            self._column_guides.append(guide)

            # Add guides for each column
            for i in range(num_cols):
                x += col_width_px
                if x < (self.template.width_mm - mr) * self.template.px_per_mm:  # Don't exceed right margin
                    guide = GuideLineItem(x, 0, x, self.template.height_px)
                    self.scene.addItem(guide)
                    self._column_guides.append(guide)
                    guide_positions.append(x)

                    if DEBUG_COLUMN_GUIDES:
                        print(f"[DEBUG] Guide {i+1}: x={x:.2f}px")
                else:
                    if DEBUG_COLUMN_GUIDES:
                        print(f"[DEBUG] Guide {i+1} skipped: x={x:.2f}px exceeds right margin")

        # Store positions in scene for itemChange() to access
        self.scene.column_guide_positions = guide_positions

        if DEBUG_COLUMN_GUIDES:
            print(f"[DEBUG] Total guides created: {len(self._column_guides)}")
            print(f"[DEBUG] Stored {len(guide_positions)} positions in scene.column_guide_positions")
            print(f"[DEBUG] Positions: {[f'{p:.2f}px' for p in guide_positions]}")
            print(f"[DEBUG] scene.column_guide_positions = {getattr(self.scene, 'column_guide_positions', 'NOT SET!')}")
            print(f"[DEBUG] Column guides setup complete\n")

        if mode == "Equal width":
            self.statusBar().showMessage(
                f"Added {num_cols} equal-width column guides", 2000
            )
        else:
            self.statusBar().showMessage(
                f"Added {len(guide_positions)} guides at {custom_width_mm}mm width", 2000
            )

    def _set_column_guides(self, mm_values: list[float]):
        """
        Create GuideLineItems at given X positions (mm).
        """
        # Clear old guides
        self._clear_column_guides()

        factor = px_per_mm_factor()

        h = self.scene.sceneRect().height()

        for mm in mm_values:
            x = mm * factor
            guide = GuideLineItem(x, 0, x, h)
            pen = QtGui.QPen(QtGui.QColor("#cccccc"))
            pen.setStyle(QtCore.Qt.DashLine)
            pen.setWidth(0)  # cosmetic
            guide.setPen(pen)
            guide.setZValue(-1000)
            guide.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, False)
            guide.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, False)
            self.scene.addItem(guide)
            self._column_guides.append(guide)

    def _apply_baseline_to_selected(self):
        """Snap selected items' Y to a baseline grid."""
        _layout.apply_baseline_to_selected(self)

    def _delete_selected_items(self):
        """Delete selected items (undoable)."""
        _layout.delete_selected_items(self)

    def _clear_column_guides(self):
        """Remove all column guides"""
        for guide in self._column_guides:
            self.scene.removeItem(guide)
        self._column_guides.clear()
        
        # *** CRITICAL: Clear positions from scene ***
        self.scene.column_guide_positions = []
        
        self.statusBar().showMessage("Cleared column guides", 2000)

    def _apply_preset(self, name: str) -> None:
        """Apply a layout preset by name."""
        _presets.apply_preset(self, name)

    def _hide_selected(self):
        """Hide selected items."""
        _layout.hide_selected(self)

    def _show_all_hidden(self):
        """Show all items previously hidden."""
        _layout.show_all_hidden(self)

    def _on_cut_changed(self, label: str):
        code = {"Full": "full", "Partial": "partial", "None": "none"}[label]
        self.printer_cfg["cut_mode"] = code
        self.save_printer_settings()

    def _on_undo_redo_changed(self, *_):
        """
        Called whenever the undo stack index changes.
        We just use it to refresh selection-dependent UI
        (Properties panel + Layers) and repaint the view.
        """
        self._on_selection_changed()
        if hasattr(self, "view") and self.view is not None:
            self.view.viewport().update()

    def _show_keyboard_shortcuts_dialog(self) -> None:
        show_keyboard_shortcuts_dialog(self)


    def _resolve_raster_settings(self) -> tuple[int, int]:
        width_px = int(self.printer_cfg.get("width_px", 0))
        dpi = int(self.printer_cfg.get("dpi", 203))
        if width_px > 0:
            return (width_px, dpi)
        target = int(round(self.template.width_px))
        if (
            getattr(self.template, "dpi", dpi) != dpi
            and getattr(self.template, "dpi", None) is not None
        ):
            target = int(round(target * (dpi / float(self.template.dpi))))
        return (target, dpi)

    def _start_worker(self, worker: PrinterWorker):
        self._workers.add(worker)
        worker.finished.connect(lambda: self._workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def closeEvent(self, e: QtGui.QCloseEvent):
        # Force autosave on close if there are unsaved changes
        # This ensures recovery works even if timer hasn't fired yet
        if self._has_unsaved_changes:
            if DEBUG_AUTOSAVE:
                print("[AUTOSAVE DEBUG] Forcing autosave on close due to unsaved changes")
            self._auto_save()

        try:
            for w in list(self._workers):
                try:
                    if hasattr(w, "stop"):
                        w.stop()
                    if hasattr(w, "quit"):
                        w.quit()
                    if hasattr(w, "wait"):
                        w.wait(3000)
                except Exception:
                    pass
            self._workers.clear()
            try:
                self.scene.selectionChanged.disconnect(self._on_selection_changed)
            except Exception:
                pass
            try:
                self.scene.changed.disconnect(self._on_scene_changed)
            except Exception:
                pass
        except Exception:
            pass
        super().closeEvent(e)
