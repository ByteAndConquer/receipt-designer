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
)
from .layers import LayerList
from .views import RulerView, PX_PER_MM
from .toolbox import Toolbox
from .properties import PropertiesPanel
from .variables import VariablePanel


# -------------------------
# App constants / QSettings
# -------------------------
ORG_NAME = "ByteSized Labs"
APP_NAME = "Receipt Lab"
APP_VERSION = "0.9.5"

QtCore.QCoreApplication.setOrganizationName(ORG_NAME)
QtCore.QCoreApplication.setApplicationName(APP_NAME)
QtCore.QCoreApplication.setApplicationVersion(APP_VERSION)

class PrintPreviewDialog(QtWidgets.QDialog):
    """Modal dialog showing print preview with zoom controls"""
    
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
        self.scene = QtWidgets.QGraphicsScene(self)
        self.view = RulerView(self)
        self.view.setScene(self.scene)
        self.view.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        # Make canvas white so red dotted margins are visible
        self.view.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
        # Force margins visible by default
        if hasattr(self.view, "setShowMargins"):
            self.view.setShowMargins(True)
        else:
            setattr(self.view, "show_margins", True)

        # Rubberband drag for multi-selection
        self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)

        # Ensure the view/viewport can take focus
        self.view.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.view.viewport().setFocusPolicy(QtCore.Qt.StrongFocus)

        # Keyboard handling on BOTH view and viewport
        self.view.installEventFilter(self)
        self.view.viewport().installEventFilter(self)

        central = QtWidgets.QWidget(self)
        lay = QtWidgets.QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self.setCentralWidget(central)

        self.scene.changed.connect(self._mark_unsaved)

    def _build_toolbars_menus(self):
        # ---- Undo/Redo ----
        act_undo = self.undo_stack.createUndoAction(self, "Undo")
        act_undo.setShortcut(QtGui.QKeySequence.Undo)
        act_undo.setToolTip("Undo last action (Ctrl+Z)")  # ← Patch 10
        
        act_redo = self.undo_stack.createRedoAction(self, "Redo")
        act_redo.setShortcut(QtGui.QKeySequence.Redo)
        act_redo.setToolTip("Redo previously undone action (Ctrl+Y or Ctrl+Shift+Z)")  # ← Patch 10

        # =============================
        # Main toolbar: file/print/printer/page
        # =============================
        tb_main = QtWidgets.QToolBar("Main")
        tb_main.setIconSize(QtCore.QSize(16, 16))
        self.addToolBar(tb_main)

        # File (quick save/load current template)
        act_save = QtGui.QAction("Save", self)
        act_save.setToolTip("Save current template to file (Ctrl+S)")  # ← Patch 10
        act_save.triggered.connect(self.save_template)
        tb_main.addAction(act_save)

        act_load = QtGui.QAction("Load", self)
        act_load.setToolTip("Open template from file (Ctrl+O)")  # ← Patch 10
        act_load.triggered.connect(self.load_template)
        tb_main.addAction(act_load)

        tb_main.addSeparator()

        act_preview = QtGui.QAction("Preview", self)
        act_preview.setToolTip("Preview how the receipt will look before printing (Ctrl+Shift+P)")  # ← Patch 10
        act_preview.triggered.connect(self.preview_print)
        tb_main.addAction(act_preview)

        # Print / Config
        act_print = QtGui.QAction("Print", self)
        act_print.setToolTip("Send template to thermal printer (Ctrl+P)")  # ← Patch 10
        act_print.triggered.connect(self.print_now)
        tb_main.addAction(act_print)

        act_conf = QtGui.QAction("Config", self)
        act_conf.setToolTip("Configure printer connection and settings")  # ← Patch 10
        act_conf.triggered.connect(self.configure_printer)
        tb_main.addAction(act_conf)

        tb_main.addSeparator()

        # Transport
        act_feed = QtGui.QAction("Feed", self)
        act_feed.setToolTip("Feed paper through printer without printing")  # ← Patch 10
        act_feed.triggered.connect(lambda: self.quick_action("feed"))
        tb_main.addAction(act_feed)

        act_cut_btn = QtGui.QAction("Cut", self)
        act_cut_btn.setToolTip("Cut paper at current position")  # ← Patch 10
        act_cut_btn.triggered.connect(lambda: self.quick_action("cut"))
        tb_main.addAction(act_cut_btn)

        tb_main.addSeparator()
        tb_main.addAction(act_undo)
        tb_main.addAction(act_redo)

        # ---- Job settings: Darkness & Cut mode ----
        tb_main.addSeparator()
        tb_main.addWidget(QtWidgets.QLabel("Darkness:"))

        self.sb_darkness = QtWidgets.QSpinBox()
        self.sb_darkness.setRange(1, 255)
        self.sb_darkness.setAccelerated(True)
        self.sb_darkness.setValue(int(self.printer_cfg.get("darkness", 180)))
        self.sb_darkness.valueChanged.connect(self._on_darkness_changed)
        self.sb_darkness.setToolTip(  # ← Patch 10
            "Print darkness level (1-255)\n"
            "Higher values = darker print\n"
            "Recommended: 150-200"
        )
        tb_main.addWidget(self.sb_darkness)

        tb_main.addSeparator()
        tb_main.addWidget(QtWidgets.QLabel("Cut:"))

        self.cb_cut = QtWidgets.QComboBox()
        self.cb_cut.addItems(["Full", "Partial", "None"])
        _cut_saved = (self.printer_cfg.get("cut_mode", "partial") or "partial").lower()
        _cut_map = {"full": "Full", "partial": "Partial", "none": "None"}
        self.cb_cut.setCurrentText(_cut_map.get(_cut_saved, "Partial"))
        self.cb_cut.currentTextChanged.connect(self._on_cut_changed)
        self.cb_cut.setToolTip(  # ← Patch 10
            "Paper cutting mode:\n"
            "• Full: Complete cut through paper\n"
            "• Partial: Perforation for easy tearing\n"
            "• None: No cutting (continuous paper)"
        )
        tb_main.addWidget(self.cb_cut)

        # ---- Printer profile selector ----
        tb_main.addSeparator()
        tb_main.addWidget(QtWidgets.QLabel("Profile:"))

        self.profile_combo = QtWidgets.QComboBox()
        self.profile_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self._refresh_profile_combo()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self.profile_combo.setToolTip("Select saved printer profile")  # ← Patch 10
        tb_main.addWidget(self.profile_combo)

        # ---- Page size controls ----
        tb_main.addSeparator()
        tb_main.addWidget(QtWidgets.QLabel("Width:"))
        self.cb_w_mm = QtWidgets.QComboBox()
        self.cb_w_mm.setEditable(True)
        self.cb_w_mm.addItems(["58 mm", "80 mm", "100 mm"])
        self.cb_w_mm.setCurrentText(f"{int(self.template.width_mm)} mm")
        self.cb_w_mm.setToolTip("Paper width in millimeters (common: 58mm, 80mm)")  # ← Patch 10
        tb_main.addWidget(self.cb_w_mm)

        tb_main.addWidget(QtWidgets.QLabel("Height:"))
        self.cb_h_mm = QtWidgets.QComboBox()
        self.cb_h_mm.setEditable(True)
        self.cb_h_mm.addItems(["50 mm", "75 mm", "200 mm", "300 mm"])
        self.cb_h_mm.setCurrentText(f"{int(self.template.height_mm)} mm")
        self.cb_h_mm.setToolTip("Paper height in millimeters")  # ← Patch 10
        tb_main.addWidget(self.cb_h_mm)

        def _apply_page():
            def parse_mm(s: str) -> float:
                s = s.lower().strip().replace("mm", "").strip()
                return float(s) if s else 80.0

            self.template.width_mm = parse_mm(self.cb_w_mm.currentText())
            self.template.height_mm = parse_mm(self.cb_h_mm.currentText())
            self.update_paper()

        self.cb_w_mm.editTextChanged.connect(lambda *_: _apply_page())
        self.cb_h_mm.editTextChanged.connect(lambda *_: _apply_page())
        self.cb_w_mm.currentTextChanged.connect(lambda *_: _apply_page())
        self.cb_h_mm.currentTextChanged.connect(lambda *_: _apply_page())

        # =============================
        # Layout toolbar: align / distrib / group / z / lock / baseline
        # =============================
        self.addToolBarBreak()
        tb_layout = QtWidgets.QToolBar("Layout")
        tb_layout.setIconSize(QtCore.QSize(16, 16))
        self.addToolBar(tb_layout)

        # ---- Align controls ----
        tb_layout.addWidget(QtWidgets.QLabel("Align:"))

        # Toggle: align to margins vs whole page
        self.act_align_use_margins = QtGui.QAction("Margins", self)
        self.act_align_use_margins.setCheckable(True)
        self.act_align_use_margins.setChecked(True)
        self.act_align_use_margins.setToolTip(
            "Align to margins vs full page:\n"
            "• Checked: Align relative to printable area (respects margins)\n"
            "• Unchecked: Align relative to full page edges"
        )
        tb_layout.addAction(self.act_align_use_margins)

        act_align_left = QtGui.QAction("⟵", self)
        act_align_left.setToolTip("Align selected items to left edge")  # ← Patch 10
        act_align_left.triggered.connect(lambda: self._align_selected("left"))
        tb_layout.addAction(act_align_left)

        act_align_hcenter = QtGui.QAction("↔", self)
        act_align_hcenter.setToolTip("Align selected items to horizontal center")  # ← Patch 10
        act_align_hcenter.triggered.connect(lambda: self._align_selected("hcenter"))
        tb_layout.addAction(act_align_hcenter)

        act_align_right = QtGui.QAction("⟶", self)
        act_align_right.setToolTip("Align selected items to right edge")  # ← Patch 10
        act_align_right.triggered.connect(lambda: self._align_selected("right"))
        tb_layout.addAction(act_align_right)

        tb_layout.addSeparator()

        act_align_top = QtGui.QAction("⟰", self)
        act_align_top.setToolTip("Align selected items to top edge")  # ← Patch 10
        act_align_top.triggered.connect(lambda: self._align_selected("top"))
        tb_layout.addAction(act_align_top)

        act_align_vcenter = QtGui.QAction("↕", self)
        act_align_vcenter.setToolTip("Align selected items to vertical center")  # ← Patch 10
        act_align_vcenter.triggered.connect(lambda: self._align_selected("vcenter"))
        tb_layout.addAction(act_align_vcenter)

        act_align_bottom = QtGui.QAction("⟱", self)
        act_align_bottom.setToolTip("Align selected items to bottom edge")  # ← Patch 10
        act_align_bottom.triggered.connect(lambda: self._align_selected("bottom"))
        tb_layout.addAction(act_align_bottom)

        # ---- Distribute ----
        tb_layout.addSeparator()
        tb_layout.addWidget(QtWidgets.QLabel("Distrib:"))

        act_dist_h = QtGui.QAction("H", self)
        act_dist_h.setToolTip("Distribute selected items evenly across horizontal space")  # ← Patch 10
        act_dist_h.triggered.connect(lambda: self._distribute_selected("h"))
        tb_layout.addAction(act_dist_h)

        act_dist_v = QtGui.QAction("V", self)
        act_dist_v.setToolTip("Distribute selected items evenly across vertical space")  # ← Patch 10
        act_dist_v.triggered.connect(lambda: self._distribute_selected("v"))
        tb_layout.addAction(act_dist_v)

        # ---- Group / Ungroup ----
        tb_layout.addSeparator()
        tb_layout.addWidget(QtWidgets.QLabel("Group:"))

        act_group = QtGui.QAction("Grp", self)
        act_group.setToolTip("Group selected items together (Ctrl+G)\nGrouped items move as one unit")  # ← Patch 10
        act_group.setShortcut("Ctrl+G")
        act_group.triggered.connect(self._group_selected)
        tb_layout.addAction(act_group)

        act_ungroup = QtGui.QAction("Ungrp", self)
        act_ungroup.setToolTip("Ungroup selected group (Ctrl+Shift+G)\nSeparates items in a group")  # ← Patch 10
        act_ungroup.setShortcut("Ctrl+Shift+G")
        act_ungroup.triggered.connect(self._ungroup_selected)
        tb_layout.addAction(act_ungroup)

        # ---- Z-order ----
        tb_layout.addSeparator()
        tb_layout.addWidget(QtWidgets.QLabel("Order:"))

        # Bring to front
        act_front = QtGui.QAction("Front", self)
        act_front.setToolTip("Bring to front\nMove selected item above all others")  # ← Patch 10
        act_front.triggered.connect(lambda: self._change_z_order("front"))
        tb_layout.addAction(act_front)

        # Send to back
        act_back = QtGui.QAction("Back", self)
        act_back.setToolTip("Send to back\nMove selected item below all others")  # ← Patch 10
        act_back.triggered.connect(lambda: self._change_z_order("back"))
        tb_layout.addAction(act_back)

        # One step forward
        act_up = QtGui.QAction("Raise", self)
        act_up.setToolTip("Bring forward\nMove selected item one layer up")  # ← Patch 10
        act_up.triggered.connect(lambda: self._change_z_order("up"))
        tb_layout.addAction(act_up)

        # One step backward
        act_down = QtGui.QAction("Lower", self)
        act_down.setToolTip("Send backward\nMove selected item one layer down")  # ← Patch 10
        act_down.triggered.connect(lambda: self._change_z_order("down"))
        tb_layout.addAction(act_down)

        # ---- Lock / Hide ----
        tb_layout.addSeparator()
        tb_layout.addWidget(QtWidgets.QLabel("Lock:"))

        act_lock = QtGui.QAction("Lock", self)
        act_lock.setToolTip("Lock selected items\nPrevents moving, resizing, and editing")  # ← Patch 10
        act_lock.triggered.connect(self._lock_selected)
        tb_layout.addAction(act_lock)

        act_unlock = QtGui.QAction("Unlock", self)
        act_unlock.setToolTip("Unlock selected items\nAllows moving, resizing, and editing")  # ← Patch 10
        act_unlock.triggered.connect(self._unlock_selected)
        tb_layout.addAction(act_unlock)

        act_hide = QtGui.QAction("Hide", self)
        act_hide.setToolTip("Hide selected items\nMakes items invisible (won't print)")  # ← Patch 10
        act_hide.triggered.connect(self._hide_selected)
        tb_layout.addAction(act_hide)

        act_show_all = QtGui.QAction("Unhide", self)
        act_show_all.setToolTip("Show all hidden items\nMakes all items visible again")  # ← Patch 10
        act_show_all.triggered.connect(self._show_all_hidden)
        tb_layout.addAction(act_show_all)

        # ---- Baseline ----
        tb_layout.addSeparator()
        tb_layout.addWidget(QtWidgets.QLabel("Baseline:"))

        self.sb_baseline_mm = QtWidgets.QDoubleSpinBox()
        self.sb_baseline_mm.setRange(0.5, 20.0)
        self.sb_baseline_mm.setDecimals(2)
        self.sb_baseline_mm.setSingleStep(0.5)
        self.sb_baseline_mm.setValue(4.0)
        self.sb_baseline_mm.setSuffix(" mm")
        self.sb_baseline_mm.setToolTip(  # ← Patch 10
            "Baseline grid spacing in millimeters\n"
            "Used to align text to consistent vertical rhythm"
        )
        tb_layout.addWidget(self.sb_baseline_mm)

        act_baseline_apply = QtGui.QAction("Apply", self)
        act_baseline_apply.setToolTip(  # ← Patch 10
            "Snap to baseline grid\n"
            "Aligns selected items' Y position to baseline grid"
        )
        act_baseline_apply.triggered.connect(self._apply_baseline_to_selected)
        tb_layout.addAction(act_baseline_apply)

        # Shortcut: Delete selected items
        self._shortcut_delete = QtGui.QShortcut(QtGui.QKeySequence.Delete, self)
        self._shortcut_delete.activated.connect(self._delete_selected_items)

        # ========== Patch 10: Duplicate shortcut ==========
        self._shortcut_duplicate = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+D"), self)
        self._shortcut_duplicate.activated.connect(self._duplicate_selected_items)
        # ========== END Patch 10 ==========

        # =============================
        # Menubar
        # =============================
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu("&File")

        act_open = QtGui.QAction("Open Template…", self)
        act_open.setShortcut("Ctrl+O")
        act_open.setToolTip("Open template from file (Ctrl+O)")
        act_open.triggered.connect(self.load_template)
        file_menu.addAction(act_open)

        act_save = QtGui.QAction("Save Template…", self)
        act_save.setShortcut("Ctrl+S")
        act_save.setToolTip("Save current template to file (Ctrl+S)")
        act_save.triggered.connect(self.save_template)
        file_menu.addAction(act_save)

        file_menu.addSeparator()
        self.recent_menu = file_menu.addMenu("Recent Files")
        self._refresh_recent_menu()
        file_menu.addSeparator()

        file_menu.addSeparator()

        act_export_png = QtGui.QAction("Export as PNG…", self)
        act_export_png.setToolTip("Export template as PNG image file")  # ← Patch 10
        act_export_png.triggered.connect(self.export_png)
        file_menu.addAction(act_export_png)

        act_export_pdf = QtGui.QAction("Export as PDF…", self)
        act_export_pdf.setToolTip("Export template as PDF document")  # ← Patch 10
        act_export_pdf.triggered.connect(self.export_pdf)
        file_menu.addAction(act_export_pdf)

        file_menu.addSeparator()

        act_file_preview = QtGui.QAction("Print Preview…", self)
        act_file_preview.setShortcut("Ctrl+Shift+P")
        act_file_preview.setToolTip("Preview how the receipt will look before printing (Ctrl+Shift+P)")  # ← Patch 10
        act_file_preview.triggered.connect(self.preview_print)
        file_menu.addAction(act_file_preview)

        act_file_print = QtGui.QAction("Print…", self)
        act_file_print.setShortcut("Ctrl+P")
        act_file_print.setToolTip("Send template to thermal printer (Ctrl+P)")  # ← Patch 10
        act_file_print.triggered.connect(self.print_now)
        file_menu.addAction(act_file_print)

        file_menu.addSeparator()

        act_exit = QtGui.QAction("Exit", self)
        act_exit.setToolTip("Exit the application")  # ← Patch 10
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # In _build_toolbars_menus(), find or create the Edit menu:
        edit_menu = menubar.addMenu("&Edit")

        # Add undo/redo if not already there
        edit_menu.addAction(act_undo)
        edit_menu.addAction(act_redo)
        edit_menu.addSeparator()

        # ========== Patch 10: Duplicate menu items ==========
        act_duplicate = QtGui.QAction("Duplicate", self)
        act_duplicate.setToolTip("Duplicate selected items (Ctrl+D)")
        act_duplicate.triggered.connect(self._duplicate_selected_items)
        edit_menu.addAction(act_duplicate)

        act_set_dup_offset = QtGui.QAction("Set Duplicate Offset…", self)
        act_set_dup_offset.setToolTip("Change the offset used when duplicating items")
        act_set_dup_offset.triggered.connect(self._set_duplicate_offset_dialog)
        edit_menu.addAction(act_set_dup_offset)
        # ========== END Patch 10 ==========

        # View
        
        self.action_margins = QtGui.QAction("Show Printable Margins", self)
        self.action_margins.setCheckable(True)
        self.action_margins.setChecked(True)
        self.action_margins.setShortcut("Ctrl+M")
        self.action_margins.setToolTip(  # ← Patch 10
            "Toggle margin guides\n"
            "Shows printable area boundaries (Ctrl+M)"
        )
        self.action_margins.toggled.connect(self._on_toggle_margins)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.action_margins)

        # Dark mode toggle
        self.action_dark_mode = QtGui.QAction("Dark Mode", self)
        self.action_dark_mode.setCheckable(True)
        self.action_dark_mode.setChecked(self.settings.value("ui/dark_mode", False, type=bool))
        self.action_dark_mode.setToolTip("Toggle dark mode appearance")
        self.action_dark_mode.toggled.connect(self._toggle_dark_mode)
        view_menu.addAction(self.action_dark_mode)

        view_menu.addSeparator()
        # NOTE: Variables panel menu item will be added in _update_view_menu()
        # which is called after _build_docks() completes

        # Insert
        insert_menu = menubar.addMenu("&Insert")

        # Text
        act_add_text = QtGui.QAction("Text", self)
        act_add_text.setShortcut("Ctrl+Shift+T")
        act_add_text.setToolTip("Insert text element (Ctrl+Shift+T)\nAdd editable text to receipt")  # ← Patch 10
        act_add_text.triggered.connect(self.add_text)
        insert_menu.addAction(act_add_text)

        # Barcode
        act_add_barcode = QtGui.QAction("Barcode", self)
        act_add_barcode.setShortcut("Ctrl+Shift+B")
        act_add_barcode.setToolTip("Insert barcode element (Ctrl+Shift+B)\nAdd scannable barcode")  # ← Patch 10
        act_add_barcode.triggered.connect(self.add_barcode)
        insert_menu.addAction(act_add_barcode)

        insert_menu.addSeparator()

        # Image
        act_add_image = QtGui.QAction("Image…", self)
        act_add_image.setShortcut("Ctrl+Shift+I")
        act_add_image.setToolTip("Insert image from file (Ctrl+Shift+I)\nAdd logo or picture")  # ← Patch 10
        act_add_image.triggered.connect(self.add_image)
        insert_menu.addAction(act_add_image)

        insert_menu.addSeparator()

        # Line
        act_add_line = QtGui.QAction("Line", self)
        act_add_line.setShortcut("Ctrl+Shift+L")
        act_add_line.setToolTip("Insert line (Ctrl+Shift+L)\nAdd horizontal or vertical line")  # ← Patch 10
        act_add_line.triggered.connect(self.add_line)
        insert_menu.addAction(act_add_line)

        # Shapes if available
        if hasattr(self, "add_rect"):
            act_add_rect = QtGui.QAction("Rectangle", self)
            act_add_rect.setShortcut("Ctrl+Shift+R")
            act_add_rect.setToolTip("Insert rectangle (Ctrl+Shift+R)\nAdd rectangular shape")  # ← Patch 10
            act_add_rect.triggered.connect(self.add_rect)
            insert_menu.addAction(act_add_rect)

        if hasattr(self, "add_circle"):
            act_add_circle = QtGui.QAction("Circle", self)
            act_add_circle.setShortcut("Ctrl+Shift+C")
            act_add_circle.setToolTip("Insert circle (Ctrl+Shift+C)\nAdd circular shape")  # ← Patch 10
            act_add_circle.triggered.connect(self.add_circle)
            insert_menu.addAction(act_add_circle)

        if hasattr(self, "add_star"):
            act_add_star = QtGui.QAction("Star", self)
            act_add_star.setShortcut("Ctrl+Shift+S")
            act_add_star.setToolTip("Insert star (Ctrl+Shift+S)\nAdd star shape")  # ← Patch 10
            act_add_star.triggered.connect(self.add_star)
            insert_menu.addAction(act_add_star)

        if hasattr(self, "add_arrow"):
            act_add_arrow = QtGui.QAction("Arrow", self)
            act_add_arrow.setShortcut("Ctrl+Shift+A")
            act_add_arrow.setToolTip("Insert arrow (Ctrl+Shift+A)\nAdd directional arrow")  # ← Patch 10
            act_add_arrow.triggered.connect(self.add_arrow)
            insert_menu.addAction(act_add_arrow)

        if hasattr(self, "add_diamond"):
            act_add_diamond = QtGui.QAction("Diamond", self)
            act_add_diamond.setShortcut("Ctrl+Shift+D")
            act_add_diamond.setToolTip("Insert diamond (Ctrl+Shift+D)\nAdd diamond shape")  # ← Patch 10
            act_add_diamond.triggered.connect(self.add_diamond)
            insert_menu.addAction(act_add_diamond)

        # Layout menu (column guides, baseline, presets)
        layout_menu = menubar.addMenu("&Layout")

        act_cols = QtGui.QAction("Set Column Guides…", self)
        act_cols.setToolTip("Create vertical column guides for alignment")  # ← Patch 10
        act_cols.triggered.connect(self._set_column_guides_dialog)
        layout_menu.addAction(act_cols)

        act_cols_clear = QtGui.QAction("Clear Column Guides", self)
        act_cols_clear.setToolTip("Remove all column guides")  # ← Patch 10
        act_cols_clear.triggered.connect(self._clear_column_guides)
        layout_menu.addAction(act_cols_clear)

        layout_menu.addSeparator()

        act_baseline_menu = QtGui.QAction("Apply Baseline to Selection", self)
        act_baseline_menu.setToolTip("Snap selected items to baseline grid")  # ← Patch 10
        act_baseline_menu.triggered.connect(self._apply_baseline_to_selected)
        layout_menu.addAction(act_baseline_menu)

        presets_menu = layout_menu.addMenu("Presets")

        act_preset_simple = QtGui.QAction("Simple Store Receipt", self)
        act_preset_simple.setToolTip("Load basic retail receipt template")  # ← Patch 10
        act_preset_simple.triggered.connect(
            lambda: self._apply_preset("simple_store_receipt")
        )
        presets_menu.addAction(act_preset_simple)

        act_preset_kitchen = QtGui.QAction("Kitchen Ticket", self)
        act_preset_kitchen.setToolTip("Load restaurant kitchen order template")  # ← Patch 10
        act_preset_kitchen.triggered.connect(
            lambda: self._apply_preset("kitchen_ticket")
        )
        presets_menu.addAction(act_preset_kitchen)

        # --- New presets ---

        act_preset_detailed = QtGui.QAction("Detailed Store Receipt", self)
        act_preset_detailed.setToolTip("Load detailed retail receipt with itemization")  # ← Patch 10
        act_preset_detailed.triggered.connect(
            lambda: self._apply_preset("detailed_store_receipt")
        )
        presets_menu.addAction(act_preset_detailed)

        act_preset_pickup = QtGui.QAction("Pickup Ticket", self)
        act_preset_pickup.setToolTip("Load order pickup ticket template")  # ← Patch 10
        act_preset_pickup.triggered.connect(
            lambda: self._apply_preset("pickup_ticket")
        )
        presets_menu.addAction(act_preset_pickup)

        act_preset_todo = QtGui.QAction("To-Do / Checklist", self)
        act_preset_todo.setToolTip("Load checklist template")  # ← Patch 10
        act_preset_todo.triggered.connect(
            lambda: self._apply_preset("todo_checklist")
        )
        presets_menu.addAction(act_preset_todo)

        act_preset_message = QtGui.QAction("Message Note", self)
        act_preset_message.setToolTip("Load message note template")  # ← Patch 10
        act_preset_message.triggered.connect(
            lambda: self._apply_preset("message_note")
        )
        presets_menu.addAction(act_preset_message)

        act_preset_fortune = QtGui.QAction("Fortune Cookie", self)
        act_preset_fortune.setToolTip("Load fortune cookie slip template")  # ← Patch 10
        act_preset_fortune.triggered.connect(
            lambda: self._apply_preset("fortune_cookie")
        )
        presets_menu.addAction(act_preset_fortune)

        # =============================
        # Help menu
        # =============================
        help_menu = menubar.addMenu("&Help")

        act_shortcuts = QtGui.QAction("Keyboard Shortcuts…", self)
        act_shortcuts.setToolTip("View all keyboard shortcuts")  # ← Patch 10
        act_shortcuts.triggered.connect(self._show_keyboard_shortcuts_dialog)
        help_menu.addAction(act_shortcuts)

    def _build_docks(self):
        # LEFT: Toolbox
        self.toolbox = Toolbox(self)
        self.toolbox.add_text.connect(self.add_text)
        self.toolbox.add_barcode.connect(self.add_barcode)
        self.toolbox.add_image.connect(self.add_image)
        self.toolbox.add_line.connect(self.add_line)
        self.toolbox.add_arrow.connect(self.add_arrow)
        self.toolbox.add_rect.connect(self.add_rect)
        self.toolbox.add_circle.connect(self.add_circle)
        self.toolbox.add_star.connect(self.add_star)
        self.toolbox.add_diamond.connect(self.add_diamond)

        dock_left = QtWidgets.QDockWidget("Toolbox", self)
        dock_left.setObjectName("ToolboxDock")
        dock_left.setWidget(self.toolbox)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock_left)

        # RIGHT: Layers
        self.layer_list = LayerList(self)
        self.layer_list.set_scene(self.scene)

        dock_layers = QtWidgets.QDockWidget("Layers", self)
        dock_layers.setObjectName("LayersDock")
        dock_layers.setWidget(self.layer_list)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock_layers)

        # RIGHT: Properties — wrapped in a scroll area
        self.props = PropertiesPanel(self)
        self.props.set_undo_stack(self.undo_stack)

        props_scroll = QtWidgets.QScrollArea()
        props_scroll.setWidget(self.props)
        props_scroll.setWidgetResizable(True)
        props_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        props_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        dock_props = QtWidgets.QDockWidget("Properties", self)
        dock_props.setObjectName("PropertiesDock")
        dock_props.setWidget(props_scroll)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock_props)

        # RIGHT: Variables
        self.variable_panel = VariablePanel(self)
        self.dock_variables = QtWidgets.QDockWidget("Variables", self)  # ← Change to self.dock_variables
        self.dock_variables.setObjectName("VariablesDock")
        self.dock_variables.setWidget(self.variable_panel)
        self.dock_variables.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable |
            QtWidgets.QDockWidget.DockWidgetFloatable
        )
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.dock_variables)

        # Tabify all right-side panels together
        self.tabifyDockWidget(dock_layers, dock_props)
        self.tabifyDockWidget(dock_props, self.dock_variables)  # ← Use self.dock_variables
        
        
        # Show Properties by default
        dock_props.raise_()
        
        # Connect variable changes to view updates
        self.variable_panel.variables_changed.connect(
            lambda: self.view.viewport().update()
        )

        # Keep panels in sync
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.scene.changed.connect(self._on_scene_changed)
        self.props.element_changed.connect(self._on_props_element_changed)
        # self.props.element_changed.connect(lambda *_: self._refresh_layers_safe())

    def _update_view_menu(self):
        """Add dock toggle actions to View menu (called after docks are built)"""
        # Find the View menu
        for action in self.menuBar().actions():
            if action.text() == "&View":
                view_menu = action.menu()
                if view_menu:
                    view_menu.addSeparator()
                    
                    # Add Variables panel toggle
                    if hasattr(self, 'dock_variables'):
                        act_variables = self.dock_variables.toggleViewAction()
                        act_variables.setText("Variables Panel")
                        view_menu.addAction(act_variables)
                break

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
        # set scene rect from Template
        w = float(self.template.width_px)
        h = float(self.template.height_px)
        self.scene.setSceneRect(0, 0, w, h)

        # expose properties that RulerView expects
        self.scene.setProperty("paper_width", w)
        self.scene.setProperty("paper_height", h)
        self.scene.setProperty("dpi", self.template.dpi)

        # margins_mm on scene: (left, top, right, bottom)
        # You wanted only left/right margins, top/bottom = 0
        self.scene.margins_mm = getattr(
            self.template,
            "margins_mm",
            (4.0, 0.0, 4.0, 0.0),
        )

        # Keep column guides spanning the full paper height
        if hasattr(self, "_column_guides"):
            for g in self._column_guides:
                line = g.line()
                g.setLine(line.x1(), 0, line.x2(), h)

        self.view.viewport().update()

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

        margins_mm = getattr(self.scene, "margins_mm", (0.0, 0.0, 0.0, 0.0))
        try:
            ml, mt, mr, mb = margins_mm
        except Exception:
            ml = mt = mr = mb = 0.0

        try:
            factor = float(PX_PER_MM) if PX_PER_MM else 1.0
        except Exception:
            factor = 1.0

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

        margins_mm = getattr(self.scene, "margins_mm", (0.0, 0.0, 0.0, 0.0))
        try:
            ml, mt, mr, mb = margins_mm
        except Exception:
            ml = mt = mr = mb = 0.0

        try:
            factor = float(PX_PER_MM) if PX_PER_MM else 1.0
        except Exception:
            factor = 1.0

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
        margins_mm = getattr(self.template, "margins_mm", (0.0, 0.0, 0.0, 0.0))
        try:
            ml, mt, mr, mb = margins_mm
        except Exception:
            ml = mt = mr = mb = 0.0

        try:
            factor = float(PX_PER_MM) if PX_PER_MM else 1.0
        except Exception:
            factor = 1.0

        base_x = ml * factor + 10.0
        base_y = mt * factor + 10.0

        p1 = QtCore.QPointF(base_x, base_y)
        p2 = QtCore.QPointF(base_x + 60.0, base_y)

        item = GArrowItem(p1, p2)
        self.scene.addItem(item)
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
            try:
                factor = float(PX_PER_MM) if PX_PER_MM else 1.0
            except Exception:
                factor = 1.0

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

            self.scene.addItem(item)
            self.template.elements.append(elem)

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
        margins_mm = getattr(self.scene, "margins_mm", (0.0, 0.0, 0.0, 0.0))
        try:
            ml, mt, mr, mb = margins_mm
        except Exception:
            ml = mt = mr = mb = 0.0

        try:
            factor = float(PX_PER_MM) if PX_PER_MM else 1.0
        except Exception:
            factor = 1.0

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
        item.undo_stack = self.undo_stack  # ← ADD THIS TOO
        item._main_window = self  # ← ADD THIS
        self.scene.addItem(item)
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
            print(f"[PRINT DEBUG] Render exception: {e}")
            return

        if img is None or img.isNull():
            QtWidgets.QMessageBox.warning(
                self, "Print Error", "Could not render the scene to an image."
            )
            print("[PRINT DEBUG] scene_to_image returned null image")
            return

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
        """Save template to file with improved error handling"""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Template", "", "Template JSON (*.json)"
        )
        if not path:
            return
        
        # Ensure .json extension
        if not path.lower().endswith('.json'):
            path += '.json'
        
        # ========== Patch 9: Collect elements with error handling ==========
        try:
            elements = []
            for it in self.scene.items():
                if isinstance(it, GItem):
                    elements.append(it.elem.to_dict())

            # Make asset paths portable (relative where possible)
            elements = self._make_elements_portable(elements, path)

            t = Template(
                width_mm=self.template.width_mm,
                height_mm=self.template.height_mm,
                dpi=self.template.dpi,
                margins_mm=self.template.margins_mm,
                elements=[Element.from_dict(e) for e in elements],
                guides=self.template.guides,
                grid=self.template.grid,
                name=self.template.name,
                version=self.template.version,
                variable_manager=self.template.variable_manager,
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Serialization Error",
                f"Could not convert template to JSON format:\n\n"
                f"Error: {type(e).__name__}: {e}\n\n"
                "One or more elements may have invalid data."
            )
            return

        # ========== Patch 9: Write file with error handling ==========
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(t.to_dict(), f, indent=2)
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                self,
                "Permission Denied",
                f"You don't have permission to write to:\n{path}\n\n"
                "Try saving to a different location or check folder permissions."
            )
            return
        except OSError as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Save Error",
                f"Could not save file:\n{path}\n\n"
                f"Error: {e}\n\n"
                "Check that you have enough disk space and the path is valid."
            )
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Unexpected Error",
                f"An unexpected error occurred while saving:\n{path}\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            return
        
        # Success - update state
        self.statusBar().showMessage(f"Saved: {path}", 3000)
        self._update_recent_files(path)
        self._current_file_path = path
        self._has_unsaved_changes = False

    def load_template(self):
        """Load template from file with improved error handling"""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Template", "", "Template JSON (*.json)"
        )
        if not path:
            return
        
        # ========== Patch 9: File reading with error handling ==========
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(
                self,
                "File Not Found",
                f"The file could not be found:\n{path}"
            )
            # Remove from recent files using normalized comparison
            self._remove_from_recent_by_normalized(path)
            return
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                self,
                "Permission Denied",
                f"You don't have permission to read this file:\n{path}\n\n"
                "Try closing other programs that might be using it."
            )
            return
        except json.JSONDecodeError as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Template File",
                f"The file is not a valid JSON template:\n{path}\n\n"
                f"Error at line {e.lineno}, column {e.colno}:\n{e.msg}"
            )
            return
        except UnicodeDecodeError:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid File Encoding",
                f"The file encoding is not supported:\n{path}\n\n"
                "Template files must be saved as UTF-8."
            )
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Load Error",
                f"An unexpected error occurred while loading:\n{path}\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            return

        # ========== Resolve relative asset paths to absolute ==========
        # This allows templates with relative paths to work after being moved
        if "elements" in data and isinstance(data["elements"], list):
            data["elements"] = self._resolve_element_paths(data["elements"], path)

        # Remove autosave metadata key if present (user may open autosave file directly)
        data.pop("_autosave_original_path", None)

        # ========== Patch 9: Parse template with specific error handling ==========
        try:
            self.template = Template.from_dict(data)
        except KeyError as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Template Data",
                f"The template file is missing required field:\n{e}\n\n"
                "This file may be corrupted or from an incompatible version."
            )
            return
        except (ValueError, TypeError) as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Template Data",
                f"The template file contains invalid data:\n\n{e}"
            )
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Template Parse Error",
                f"Could not parse template data:\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            return

        # ========== Patch 9: Build scene with error handling ==========
        try:
            self.scene.clear()
            for e in self.template.elements:
                item = GItem(e)
                item.undo_stack = self.undo_stack
                item._main_window = self 
                self.scene.addItem(item)
                item.setPos(e.x, e.y)

            self.update_paper()
            self._refresh_layers_safe()
            self._refresh_variable_panel()

            # Patch 3 additions:
            self._current_file_path = path
            self._update_recent_files(path)
            self._has_unsaved_changes = False
            self.undo_stack.clear()
            self._clear_column_guides()

            self.statusBar().showMessage(f"Loaded: {path}", 3000)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Scene Build Error",
                f"Error building scene from template:\n\n"
                f"Error: {type(e).__name__}: {e}\n\n"
                "The template may be partially loaded."
            )

    def _mark_unsaved(self):
        """Mark that changes have been made (called when scene changes)"""
        self._has_unsaved_changes = True

    def _auto_save(self):
        """Auto-save current template to temp location every 60 seconds"""
        if not self._has_unsaved_changes:
            return  # Nothing has changed since last save
        
        if not self.scene.items():
            return  # Nothing to save
        
        temp_dir = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.TempLocation
        )
        if not temp_dir:
            print("Auto-save failed: No writable temp directory available")
            return
        
        autosave_path = os.path.join(temp_dir, "receipt_designer_autosave.json")
        
        # ========== Patch 9: Serialization with specific error handling ==========
        try:
            # Collect elements from scene
            elements = []
            for it in self.scene.items():
                if isinstance(it, GItem):
                    elements.append(it.elem.to_dict())

            # Make asset paths portable if we have a saved template path
            # (allows recovery to work correctly when moved to another machine)
            if self._current_file_path:
                elements = self._make_elements_portable(elements, self._current_file_path)

            # Create template snapshot
            t = Template(
                width_mm=self.template.width_mm,
                height_mm=self.template.height_mm,
                dpi=self.template.dpi,
                margins_mm=self.template.margins_mm,
                elements=[Element.from_dict(e) for e in elements],
                guides=self.template.guides,
                grid=self.template.grid,
                name=self.template.name,
                version=self.template.version,
                variable_manager=self.template.variable_manager,
            )
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            # Don't show dialog for auto-save serialization failures, just log
            print(f"Auto-save serialization failed: {type(e).__name__}: {e}")
            return
        except Exception as e:
            print(f"Auto-save unexpected serialization error: {type(e).__name__}: {e}")
            return
        
        # ========== Atomic write to prevent corruption on crash/power loss ==========
        tmp_path = autosave_path + ".tmp"
        try:
            # Prepare autosave data with original file path for recovery
            autosave_data = t.to_dict()
            # Store original template path so relative assets can be resolved on recovery
            if self._current_file_path:
                autosave_data["_autosave_original_path"] = self._current_file_path

            # Write to temp file first
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(autosave_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk

            # Atomically replace the final file (Windows-safe)
            os.replace(tmp_path, autosave_path)

            # Brief status update on success
            self.statusBar().showMessage("Auto-saved", 2000)

        except PermissionError:
            print(f"Auto-save permission denied: {autosave_path}")
        except OSError as e:
            print(f"Auto-save I/O error: {e}")
        except Exception as e:
            print(f"Auto-save unexpected write error: {type(e).__name__}: {e}")
        finally:
            # Clean up temp file if it still exists (failed before replace)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def _load_crash_recovery(self):
        """Check for auto-saved file on startup and offer to restore"""
        temp_dir = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.TempLocation
        )
        if not temp_dir:
            return
        
        autosave_path = os.path.join(temp_dir, "receipt_designer_autosave.json")
        
        if not os.path.exists(autosave_path):
            return
        
        # Ask user if they want to restore
        reply = QtWidgets.QMessageBox.question(
            self,
            "Recover Auto-saved Work?",
            "An auto-saved file was found. Would you like to restore it?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                with open(autosave_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Resolve relative asset paths using original template location
                original_path = data.pop("_autosave_original_path", None)
                if original_path and "elements" in data and isinstance(data["elements"], list):
                    data["elements"] = self._resolve_element_paths(data["elements"], original_path)
                    # Restore the current file path so subsequent saves work correctly
                    self._current_file_path = original_path

                self.template = Template.from_dict(data)
                
                # Clear scene and rebuild
                self.scene.clear()
                for e in self.template.elements:
                    item = GItem(e)
                    item.undo_stack = self.undo_stack
                    item._main_window = self
                    self.scene.addItem(item)
                    item.setPos(e.x, e.y)
                
                self.update_paper()
                self._refresh_layers_safe()
                self._refresh_variable_panel()
                self.statusBar().showMessage("Auto-saved work restored", 3000)
                
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Recovery Failed",
                    f"Could not restore auto-saved file: {e}"
                )
        
        # Delete auto-save file after handling (whether accepted or not)
        try:
            os.remove(autosave_path)
        except:
            pass

    # ------------ Recent Files Helpers ------------

    def _normalize_path(self, path: str) -> str:
        """
        Normalize a file path for consistent comparison and deduplication.

        On Windows this ensures paths like 'C:/foo/bar.json' and 'c:\\foo\\BAR.JSON'
        are recognized as the same file.

        Returns normalized path for comparison; original path is kept for display.
        """
        if not path:
            return ""
        # Expand user home directory if present
        path = os.path.expanduser(path)
        # Convert to absolute path
        path = os.path.abspath(path)
        # Normalize separators and resolve .. / .
        path = os.path.normpath(path)
        # Normalize case on Windows (lowercase on Windows, unchanged on Unix)
        path = os.path.normcase(path)
        return path

    def _dedupe_recent_files(self, paths: list) -> list:
        """
        Remove duplicate paths from recent files list based on normalized paths.

        Preserves order (first occurrence wins) and keeps display-friendly paths.
        """
        seen_normalized = set()
        deduped = []
        for path in paths:
            norm = self._normalize_path(path)
            if norm and norm not in seen_normalized:
                seen_normalized.add(norm)
                deduped.append(path)
        return deduped

    def _remove_from_recent_by_normalized(self, path_to_remove: str) -> None:
        """
        Remove a path from recent files, matching by normalized path.

        This handles cases where the stored path has different casing/slashes.
        """
        norm_to_remove = self._normalize_path(path_to_remove)
        recent = self.settings.value("recent_files", [], type=list)

        # Filter out any path that normalizes to the same value
        updated = [p for p in recent if self._normalize_path(p) != norm_to_remove]

        if len(updated) != len(recent):
            self.settings.setValue("recent_files", updated)
            self._refresh_recent_menu()

    # ------------ Portable Asset Path Helpers ------------

    def _make_asset_path_portable(self, asset_path: str, template_path: str) -> str:
        """
        Convert an absolute asset path to relative if it's inside the template directory.

        Args:
            asset_path: The asset file path (e.g., image_path from an Element)
            template_path: The path to the template JSON file being saved

        Returns:
            Relative path if asset is under template_dir, else original path unchanged.
        """
        if not asset_path or not template_path:
            return asset_path

        # Skip if already relative
        if not os.path.isabs(asset_path):
            return asset_path

        try:
            template_dir = os.path.dirname(os.path.abspath(template_path))
            asset_abs = os.path.abspath(asset_path)

            # Normalize for comparison (handles case on Windows)
            template_dir_norm = os.path.normcase(os.path.normpath(template_dir))
            asset_abs_norm = os.path.normcase(os.path.normpath(asset_abs))

            # Check if asset is under template directory
            # Use os.path.commonpath for reliable prefix checking
            try:
                common = os.path.commonpath([template_dir_norm, asset_abs_norm])
                if common == template_dir_norm:
                    # Asset is under template dir - make relative
                    rel_path = os.path.relpath(asset_abs, template_dir)
                    return rel_path
            except ValueError:
                # Different drives on Windows (e.g., C: vs D:)
                pass

        except Exception:
            # Any error - keep original path
            pass

        return asset_path

    def _resolve_asset_path(self, asset_path: str, template_path: str) -> str:
        """
        Resolve an asset path, converting relative paths to absolute based on template location.

        Args:
            asset_path: The asset file path from the template (may be relative or absolute)
            template_path: The path to the template JSON file being loaded

        Returns:
            Absolute path if input was relative, else original path unchanged.
        """
        if not asset_path:
            return asset_path

        # If already absolute, return as-is
        if os.path.isabs(asset_path):
            return asset_path

        # Relative path - resolve against template directory
        if not template_path:
            return asset_path

        try:
            template_dir = os.path.dirname(os.path.abspath(template_path))
            resolved = os.path.normpath(os.path.join(template_dir, asset_path))
            return resolved
        except Exception:
            # Any error - keep original path
            return asset_path

    def _make_elements_portable(self, elements: list, template_path: str) -> list:
        """
        Process element dicts to make asset paths portable (relative where possible).

        Args:
            elements: List of element dicts (from to_dict())
            template_path: The template file path being saved to

        Returns:
            New list of element dicts with portable paths
        """
        if not template_path:
            return elements

        result = []
        for elem_dict in elements:
            # Make a copy to avoid mutating original
            elem_copy = dict(elem_dict)

            # Convert image_path to relative if eligible
            if elem_copy.get("image_path"):
                elem_copy["image_path"] = self._make_asset_path_portable(
                    elem_copy["image_path"], template_path
                )

            result.append(elem_copy)

        return result

    def _resolve_element_paths(self, elements: list, template_path: str) -> list:
        """
        Process element dicts to resolve relative asset paths to absolute.

        Args:
            elements: List of element dicts (from template JSON)
            template_path: The template file path being loaded from

        Returns:
            New list of element dicts with resolved absolute paths
        """
        if not template_path:
            return elements

        result = []
        for elem_dict in elements:
            # Make a copy to avoid mutating original
            elem_copy = dict(elem_dict)

            # Resolve image_path if relative
            if elem_copy.get("image_path"):
                elem_copy["image_path"] = self._resolve_asset_path(
                    elem_copy["image_path"], template_path
                )

            result.append(elem_copy)

        return result

    def _copy_image_to_assets(self, source_path: str) -> str | None:
        """
        Copy an image file into the template's assets/ folder.

        Args:
            source_path: Absolute path to the source image file

        Returns:
            Relative path to the copied file (e.g., "assets/logo.png"), or None if copy failed/cancelled.
        """
        import shutil

        template_path = self._current_file_path
        if not template_path:
            return None

        try:
            template_dir = os.path.dirname(os.path.abspath(template_path))
            assets_dir = os.path.join(template_dir, "assets")

            # Create assets/ directory if needed
            os.makedirs(assets_dir, exist_ok=True)

            # Get original filename
            original_name = os.path.basename(source_path)
            base, ext = os.path.splitext(original_name)

            # Handle name collisions: logo.png -> logo_2.png -> logo_3.png
            dest_name = original_name
            dest_path = os.path.join(assets_dir, dest_name)
            counter = 2
            while os.path.exists(dest_path):
                dest_name = f"{base}_{counter}{ext}"
                dest_path = os.path.join(assets_dir, dest_name)
                counter += 1

            # Copy the file
            shutil.copy2(source_path, dest_path)

            # Return relative path from template directory
            rel_path = os.path.relpath(dest_path, template_dir)
            return rel_path

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Copy Failed",
                f"Could not copy image to assets folder:\n\n{e}\n\n"
                "The original file will be linked instead."
            )
            return None

    def _refresh_recent_menu(self):
        """Refresh the Recent Files menu from settings"""
        if not hasattr(self, 'recent_menu'):
            return
        
        self.recent_menu.clear()
        
        recent = self.settings.value("recent_files", [], type=list)
        
        if not recent:
            act_none = self.recent_menu.addAction("(No recent files)")
            act_none.setEnabled(False)
            return
        
        # Show up to 10 recent files
        for path in recent[:10]:
            if not os.path.exists(path):
                continue
            
            # Show filename, full path in tooltip
            filename = os.path.basename(path)
            act = self.recent_menu.addAction(filename)
            act.setToolTip(path)
            # Use lambda with default argument to capture path correctly
            act.triggered.connect(lambda checked, p=path: self._load_template_path(p))
        
        self.recent_menu.addSeparator()
        
        act_clear = self.recent_menu.addAction("Clear Recent Files")
        act_clear.triggered.connect(self._clear_recent_files)

    def _update_recent_files(self, path: str):
        """Add a file to the recent files list with normalized deduplication."""
        if not path:
            return

        # Normalize for storage (keeps consistent format)
        path = os.path.abspath(path)
        norm_path = self._normalize_path(path)

        recent = self.settings.value("recent_files", [], type=list)

        # Remove any existing entry that normalizes to the same path
        # (handles different casing/slashes pointing to same file)
        recent = [p for p in recent if self._normalize_path(p) != norm_path]

        # Add to front
        recent.insert(0, path)

        # Dedupe (in case of any edge cases) and cap at 10
        recent = self._dedupe_recent_files(recent)[:10]
        
        self.settings.setValue("recent_files", recent)
        self._refresh_recent_menu()

    def _load_template_path(self, path: str):
        """Load template from a specific file path with improved error handling"""
        # ========== Validate file exists ==========
        if not os.path.exists(path):
            reply = QtWidgets.QMessageBox.question(
                self,
                "File Not Found",
                f"The file no longer exists:\n{path}\n\n"
                "Remove it from recent files?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )

            if reply == QtWidgets.QMessageBox.Yes:
                # Use normalized removal to handle casing/slash differences
                self._remove_from_recent_by_normalized(path)
            return
        
        # ========== Patch 9: Load file with specific error handling ==========
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                self,
                "Permission Denied",
                f"You don't have permission to read this file:\n{path}\n\n"
                "Try closing other programs that might be using it."
            )
            return
        except json.JSONDecodeError as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Template File",
                f"The file is not a valid JSON template:\n{path}\n\n"
                f"Error at line {e.lineno}, column {e.colno}:\n{e.msg}"
            )
            return
        except UnicodeDecodeError:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid File Encoding",
                f"The file encoding is not supported:\n{path}\n\n"
                "Template files must be saved as UTF-8."
            )
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Load Error",
                f"An unexpected error occurred while loading:\n{path}\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            return

        # ========== Resolve relative asset paths to absolute ==========
        # This allows templates with relative paths to work after being moved
        if "elements" in data and isinstance(data["elements"], list):
            data["elements"] = self._resolve_element_paths(data["elements"], path)

        # Remove autosave metadata key if present (user may open autosave file directly)
        data.pop("_autosave_original_path", None)

        # ========== Patch 9: Parse template with specific error handling ==========
        try:
            self.template = Template.from_dict(data)
        except KeyError as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Template Data",
                f"The template file is missing required field:\n{e}\n\n"
                "This file may be corrupted or from an incompatible version."
            )
            return
        except (ValueError, TypeError) as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Invalid Template Data",
                f"The template file contains invalid data:\n\n{e}"
            )
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Template Parse Error",
                f"Could not parse template data:\n\n"
                f"Error: {type(e).__name__}: {e}"
            )
            return

        # ========== Patch 9: Build scene with error handling ==========
        try:
            self.scene.clear()
            for e in self.template.elements:
                item = GItem(e)
                item.undo_stack = self.undo_stack
                item._main_window = self
                self.scene.addItem(item)
                item.setPos(e.x, e.y)
            
            self.update_paper()
            self._refresh_layers_safe()
            self._refresh_variable_panel()

            self._current_file_path = path
            self._update_recent_files(path)  # Move to top of recent list
            self._has_unsaved_changes = False
            self.undo_stack.clear()
            self._clear_column_guides()

            self.statusBar().showMessage(f"Loaded: {os.path.basename(path)}", 3000)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Scene Build Error",
                f"Error building scene from template:\n\n"
                f"Error: {type(e).__name__}: {e}\n\n"
                "The template may be partially loaded."
            )

    def _clear_recent_files(self):
        """Clear the recent files list with confirmation"""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Clear Recent Files",
            "Are you sure you want to clear the recent files list?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self.settings.setValue("recent_files", [])
            self._refresh_recent_menu()
            self.statusBar().showMessage("Recent files cleared", 2000)

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
        """
        Fetch a random fortune.

        Returns:
            (fortune_text, lucky_numbers_str)

        - Uses https://api.viewbits.com/v1/fortunecookie?mode=random
        - Falls back to a local list + random numbers if anything fails.
        """
        fallback_fortunes = [
            "You will fix one bug and discover three more.",
            "A receipt you print today will make someone smile.",
            "Unexpected joy is hiding in a tiny project.",
            "Your next idea will be delightfully unhinged.",
            "You are one refactor away from greatness.",
            "Today’s chaos is tomorrow’s funny story.",
            "Your work will impress someone who never says it.",
        ]

        FORTUNE_API_URL = "https://api.viewbits.com/v1/fortunecookie?mode=random"

        def _fallback() -> tuple[str, str]:
            text = random.choice(fallback_fortunes)
            nums = sorted(random.sample(range(1, 60), 6))
            lucky_str = " ".join(f"{n:02d}" for n in nums)
            return text, lucky_str

        try:
            with urllib.request.urlopen(FORTUNE_API_URL, timeout=3.0) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")

            data = json.loads(raw)

            # Expected shape:
            # {
            #   "text": "...",
            #   "numbers": "26, 49, 94, 31, 63, 49",
            #   ...
            # }
            text = str(data.get("text", "")).strip()
            numbers_raw = str(data.get("numbers", "")).strip()

            if not text:
                raise ValueError("No fortune text in API response")

            lucky_str = ""
            if numbers_raw:
                # clean up "26, 49, 94, 31, 63, 49" -> "26 49 94 31 63 49"
                parts = [
                    p.strip()
                    for p in numbers_raw.replace("Lucky Numbers:", "")
                                        .replace("Lucky numbers:", "")
                                        .split(",")
                    if p.strip()
                ]
                if parts:
                    lucky_str = " ".join(parts)

            if not lucky_str:
                # generate some if the API gave nothing usable
                nums = sorted(random.sample(range(1, 60), 6))
                lucky_str = " ".join(f"{n:02d}" for n in nums)

            return text, lucky_str

        except Exception as e:
            print("[Fortune] API failed, using fallback:", e)
            return _fallback()

    def _maybe_refresh_fortune_cookie(self) -> bool:
        """
        If the scene already has a 'fortune_cookie' layout, just refresh
        the text (fortune + lucky numbers) and keep all geometry/styling.

        Returns True if it handled the refresh, False if caller should
        build a new layout from scratch.
        """
        from .items import GItem

        # Find existing fortune-cookie elements
        header_elem = None
        body_elem = None
        lucky_elem = None

        for it in self.scene.items():
            if not isinstance(it, GItem):
                continue
            e = getattr(it, "elem", None)
            if e is None:
                continue
            if getattr(e, "template_id", "") != "fortune_cookie":
                continue

            slot = getattr(e, "slot", "")
            if slot == "header":
                header_elem = e
            elif slot == "body":
                body_elem = e
            elif slot == "lucky":
                lucky_elem = e

        # If we didn't find any, fall back to full preset build
        if not (body_elem or lucky_elem):
            return False

        # Get a new fortune
        fortune_text, lucky_raw = self._get_random_fortune()

        parts = [p.strip() for p in lucky_raw.replace(",", " ").split() if p.strip()]
        lucky_line = "  ".join(parts) if parts else lucky_raw

        # Update only the text, keep fonts/geometry as-is
        if body_elem is not None:
            body_elem.text = fortune_text

        if lucky_elem is not None:
            lucky_elem.text = f"Lucky numbers:\n{lucky_line}"

        # Nuke caches for any fortune-cookie items so they repaint
        from .items import GItem
        for it in self.scene.items():
            if isinstance(it, GItem):
                e = getattr(it, "elem", None)
                if e is None:
                    continue
                if getattr(e, "template_id", "") == "fortune_cookie":
                    it._cache_qimage = None
                    it._cache_key = None
                    it.update()

        self.scene.update()
        self._refresh_layers_safe()
        self.statusBar().showMessage("Refreshed fortune", 2000)
        return True

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
        d = QtWidgets.QDialog(self)
        d.setWindowTitle("Printer Configuration")
        form = QtWidgets.QFormLayout(d)

        iface = QtWidgets.QComboBox()
        iface_map = {
            "network": "Network (LAN)",
            "usb": "USB Direct",
            "serial": "Serial (RS-232)",
        }
        iface_rev = {v: k for k, v in iface_map.items()}
        iface.addItems(iface_map.values())
        iface.setCurrentText(
            iface_map.get(self.printer_cfg.get("interface", "network"), "Network (LAN)")
        )

        host = QtWidgets.QLineEdit(self.printer_cfg.get("host", "192.168.1.50"))
        port = QtWidgets.QSpinBox()
        port.setRange(1, 65535)
        port.setValue(int(self.printer_cfg.get("port", 9100)))

        darkness = QtWidgets.QSpinBox()
        darkness.setRange(1, 255)
        darkness.setValue(int(self.printer_cfg.get("darkness", 200)))

        dpi = QtWidgets.QSpinBox()
        dpi.setRange(100, 600)
        dpi.setValue(int(self.printer_cfg.get("dpi", 203)))

        width_px = QtWidgets.QSpinBox()
        width_px.setRange(0, 2048)
        width_px.setValue(int(self.printer_cfg.get("width_px", 0)))
        width_px.setToolTip("Set to 512 to force legacy-style width. 0 disables fixed width.")

        threshold = QtWidgets.QSpinBox()
        threshold.setRange(0, 255)
        threshold.setValue(int(self.printer_cfg.get("threshold", 180)))

        cut_mode = QtWidgets.QComboBox()
        cut_label_map = {"full": "Full", "partial": "Partial", "none": "None"}
        cut_mode.addItems(cut_label_map.values())
        saved_cut = (self.printer_cfg.get("cut_mode", "partial") or "partial").lower()
        cut_mode.setCurrentText(cut_label_map.get(saved_cut, "Partial"))

        timeout_sb = QtWidgets.QDoubleSpinBox()
        timeout_sb.setRange(1.0, 120.0)
        timeout_sb.setDecimals(1)
        timeout_sb.setSingleStep(1.0)
        timeout_sb.setValue(float(self.printer_cfg.get("timeout", 30.0)))

        profile_edit = QtWidgets.QLineEdit(self.printer_cfg.get("profile", "TM-T88IV"))
        profile_edit.setPlaceholderText("e.g. TM-T88IV, default, etc.")

        form.addRow("Interface:", iface)
        form.addRow("Host:", host)
        form.addRow("Port:", port)
        form.addRow("Darkness (1–255):", darkness)
        form.addRow("DPI (fallback):", dpi)
        form.addRow("Pixel Width (0 = auto):", width_px)
        form.addRow("Threshold (0–255):", threshold)
        form.addRow("Cut mode:", cut_mode)
        form.addRow("Timeout (seconds):", timeout_sb)
        form.addRow("ESC/POS profile:", profile_edit)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        form.addRow(btns)

        def _apply():
            label = cut_mode.currentText()
            self.printer_cfg.update(
                {
                    "interface": iface_rev.get(iface.currentText(), "network"),
                    "host": host.text().strip(),
                    "port": int(port.value()),
                    "darkness": int(darkness.value()),
                    "dpi": int(dpi.value()),
                    "width_px": int(width_px.value()),
                    "threshold": int(threshold.value()),
                    "cut_mode": {"Full": "full", "Partial": "partial", "None": "none"}[
                        label
                    ],
                    "timeout": float(timeout_sb.value()),
                    "profile": profile_edit.text().strip() or "TM-T88IV",
                }
            )
            self.save_printer_settings()
            d.accept()

        btns.accepted.connect(_apply)
        btns.rejected.connect(d.reject)
        d.exec()

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
                try:
                    factor = float(PX_PER_MM) if PX_PER_MM else 1.0
                except Exception:
                    factor = 1.0

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
        items = self.scene.selectedItems()
        if not items:
            return

        for it in items:
            if not isinstance(it, QtWidgets.QGraphicsItem):
                continue
            pos = it.pos()
            new_x = pos.x() + dx
            new_y = pos.y() + dy
            it.setPos(new_x, new_y)
            if hasattr(it, "elem"):
                try:
                    it.elem.x = new_x
                    it.elem.y = new_y
                except Exception:
                    pass

    def _duplicate_selected_items(self):
        """Duplicate selected items with remembered offset"""
        items = self.scene.selectedItems()
        if not items:
            return

        new_items = []
        for it in items:
            if isinstance(it, GItem) and hasattr(it, "elem"):
                try:
                    e_dict = it.elem.to_dict()
                    new_elem = Element.from_dict(e_dict)
                except Exception:
                    continue
                
                # ========== Patch 10: Use remembered offset instead of fixed 5.0 ==========
                new_elem.x = float(getattr(it.elem, "x", 0.0)) + self._last_duplicate_offset.x()
                new_elem.y = float(getattr(it.elem, "y", 0.0)) + self._last_duplicate_offset.y()
                # ========== END Patch 10 ==========
                
                new_item = GItem(new_elem)
                new_item.undo_stack = self.undo_stack  # ← ADD THIS TOO
                new_item._main_window = self  # ← ADD THIS
                self.scene.addItem(new_item)
                new_item.setPos(new_elem.x, new_elem.y)
                new_items.append(new_item)

        if new_items:
            self.scene.clearSelection()
            for ni in new_items:
                ni.setSelected(True)
            self._refresh_layers_safe()
            
            # ========== Patch 10: Show status message with offset ==========
            self.statusBar().showMessage(
                f"Duplicated {len(new_items)} item(s) at offset "
                f"({self._last_duplicate_offset.x():.0f}, {self._last_duplicate_offset.y():.0f}) px",
                3000
            )
            # ========== END Patch 10 ==========

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
        """Allow user to customize duplicate offset"""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Set Duplicate Offset")
        layout = QtWidgets.QFormLayout(dialog)
        
        sb_x = QtWidgets.QDoubleSpinBox()
        sb_x.setRange(-1000, 1000)
        sb_x.setValue(self._last_duplicate_offset.x())
        sb_x.setSuffix(" px")
        sb_x.setDecimals(0)
        
        sb_y = QtWidgets.QDoubleSpinBox()
        sb_y.setRange(-1000, 1000)
        sb_y.setValue(self._last_duplicate_offset.y())
        sb_y.setSuffix(" px")
        sb_y.setDecimals(0)
        
        layout.addRow("Horizontal offset:", sb_x)
        layout.addRow("Vertical offset:", sb_y)
        
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self._last_duplicate_offset = QtCore.QPointF(sb_x.value(), sb_y.value())
            self.statusBar().showMessage(
                f"Duplicate offset set to ({sb_x.value():.0f}, {sb_y.value():.0f}) px",
                3000
            )

    def _on_darkness_changed(self, val: int):
        self.printer_cfg["darkness"] = int(val)
        self.save_printer_settings()

    def _align_selected(self, mode: str):
        """
        Align selected items to either:
        - the page (full scene rect), or
        - the printable area (margins),
        depending on self.act_align_use_margins.

        Locked items (data(0) == 'locked') are not moved.
        """
        from .items import GItem, GRectItem, GEllipseItem, GStarItem, GLineItem, GDiamondItem

        items = [
            it
            for it in self.scene.selectedItems()
            if isinstance(it, (GItem, GRectItem, GEllipseItem, GStarItem, GLineItem, GDiamondItem))
            and it.data(0) != "locked"
        ]
        if not items:
            return

        scene_rect = self.scene.sceneRect()
        page_w = scene_rect.width()
        page_h = scene_rect.height()

        margins_mm = getattr(self.scene, "margins_mm", (0.0, 0.0, 0.0, 0.0))
        try:
            ml, mt, mr, mb = margins_mm
        except Exception:
            ml = mt = mr = mb = 0.0

        try:
            factor = float(PX_PER_MM) if PX_PER_MM else 1.0
        except Exception:
            factor = 1.0

        margin_left_x = ml * factor
        margin_right_x = page_w - (mr * factor)
        margin_top_y = mt * factor
        margin_bottom_y = page_h - (mb * factor)

        use_margins = getattr(self, "act_align_use_margins", None)
        use_margins = bool(use_margins and self.act_align_use_margins.isChecked())

        if use_margins:
            area_left_x = margin_left_x
            area_right_x = margin_right_x
            area_top_y = margin_top_y
            area_bottom_y = margin_bottom_y
        else:
            area_left_x = 0.0
            area_right_x = page_w
            area_top_y = 0.0
            area_bottom_y = page_h

        # target centers
        area_hcenter = (area_left_x + area_right_x) / 2.0
        area_vcenter = (area_top_y + area_bottom_y) / 2.0

        for it in items:
            r = it.sceneBoundingRect()
            dx = 0.0
            dy = 0.0

            # Horizontal alignment
            if mode == "left":
                dx = area_left_x - r.left()
            elif mode == "hcenter":
                dx = area_hcenter - r.center().x()
            elif mode == "right":
                dx = area_right_x - r.right()

            # Vertical alignment
            if mode == "top":
                dy = area_top_y - r.top()
            elif mode == "vcenter":
                dy = area_vcenter - r.center().y()
            elif mode == "bottom":
                dy = area_bottom_y - r.bottom()

            if dx == 0.0 and dy == 0.0:
                continue

            it.moveBy(dx, dy)

            # keep elem in sync for GItem-based elements
            if hasattr(it, "elem"):
                try:
                    it.elem.x = float(it.pos().x())
                    it.elem.y = float(it.pos().y())
                except Exception:
                    pass

        self._refresh_layers_safe()

    def _distribute_selected(self, axis: str):
        """
        Distribute selected items evenly along axis:
        axis == 'h' -> horizontal (X centers)
        axis == 'v' -> vertical (Y centers)

        Locked items (data(0) == 'locked') are not moved.
        """
        from .items import GItem, GRectItem, GEllipseItem, GStarItem, GLineItem, GDiamondItem

        items = [
            it
            for it in self.scene.selectedItems()
            if isinstance(it, (GItem, GRectItem, GEllipseItem, GStarItem, GLineItem, GDiamondItem))
            and it.data(0) != "locked"
        ]
        if len(items) < 3:
            return

        data = []
        for it in items:
            br = it.boundingRect()
            pos = it.pos()
            cx = pos.x() + br.width() / 2.0
            cy = pos.y() + br.height() / 2.0
            data.append((it, pos, br, cx, cy))

        if axis == "h":
            data.sort(key=lambda d: d[3])  # center X
            first_c = data[0][3]
            last_c = data[-1][3]
            if last_c == first_c:
                return
            step = (last_c - first_c) / (len(data) - 1)

            for i, (it, pos, br, cx, cy) in enumerate(data):
                if i == 0 or i == len(data) - 1:
                    continue
                target_cx = first_c + step * i
                new_x = target_cx - br.width() / 2.0
                new_y = pos.y()
                it.setPos(new_x, new_y)
                if hasattr(it, "elem"):
                    try:
                        it.elem.x = float(new_x)
                        it.elem.y = float(new_y)
                    except Exception:
                        pass

        elif axis == "v":
            data.sort(key=lambda d: d[4])  # center Y
            first_c = data[0][4]
            last_c = data[-1][4]
            if last_c == first_c:
                return
            step = (last_c - first_c) / (len(data) - 1)

            for i, (it, pos, br, cx, cy) in enumerate(data):
                if i == 0 or i == len(data) - 1:
                    continue
                target_cy = first_c + step * i
                new_y = target_cy - br.height() / 2.0
                new_x = pos.x()
                it.setPos(new_x, new_y)
                if hasattr(it, "elem"):
                    try:
                        it.elem.x = float(new_x)
                        it.elem.y = float(new_y)
                    except Exception:
                        pass

    def _group_selected(self):
        """
        Group selected items into a QGraphicsItemGroup (undoable).
        """
        sel = self.scene.selectedItems()
        # Don't group groups into more groups for now
        items = [it for it in sel if not isinstance(it, QtWidgets.QGraphicsItemGroup)]
        if len(items) < 2:
            return

        cmd = GroupItemsCmd(self.scene, items, text="Group items")
        self.undo_stack.push(cmd)
        self._refresh_layers_safe()

    def _ungroup_selected(self):
        """
        Ungroup any selected QGraphicsItemGroup (undoable).
        """
        groups = [
            it
            for it in self.scene.selectedItems()
            if isinstance(it, QtWidgets.QGraphicsItemGroup)
        ]
        if not groups:
            return

        cmd = UngroupItemsCmd(self.scene, groups, text="Ungroup items")
        self.undo_stack.push(cmd)
        self._refresh_layers_safe()

    def _change_z_order(self, mode: str):
        """
        mode:
            'front' -> bring to front
            'back'  -> send to back
            'up'    -> bring forward
            'down'  -> send backward
        """
        sel = self.scene.selectedItems()
        if not sel:
            return

        all_items = self.scene.items()
        if not all_items:
            return

        z_values = [it.zValue() for it in all_items]
        max_z = max(z_values)
        min_z = min(z_values)

        if mode == "front":
            base = max_z + 1.0
            for idx, it in enumerate(sel):
                it.setZValue(base + idx)

        elif mode == "back":
            base = min_z - 1.0
            for idx, it in enumerate(sel):
                it.setZValue(base - idx)

        elif mode == "up":
            for it in sel:
                it.setZValue(it.zValue() + 1.0)

        elif mode == "down":
            for it in sel:
                it.setZValue(it.zValue() - 1.0)

        self._refresh_layers_safe()

    def _lock_selected(self):
        """
        Lock selected items: prevent moving/resizing, but keep them selectable.
        """
        for it in self.scene.selectedItems():
            it.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, False)
            # still selectable so you can unlock / edit properties
            it.setData(0, "locked")

    def _unlock_selected(self):
        """
        Unlock selected items (re-allow movement).
        """
        for it in self.scene.selectedItems():
            if it.data(0) == "locked":
                it.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, True)
                it.setData(0, None)

    def _set_column_guides_dialog(self):
        """Show dialog to set column guides with width options"""
        dialog = QtWidgets.QDialog(self)
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
        def on_mode_changed(mode):
            is_custom = (mode == "Custom width")
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
            return
        
        # Get values
        num_cols = sb_cols.value()
        mode = combo_mode.currentText()
        custom_width_mm = sb_width.value()
        
        self._clear_column_guides()
        
        # Get margins from margins_mm tuple (left, top, right, bottom)
        ml, mt, mr, mb = self.template.margins_mm
        
        # ========== DEBUG OUTPUT START ==========
        print(f"\n[DEBUG] Column Guides Creation")
        print(f"[DEBUG] Mode: {mode}")
        print(f"[DEBUG] Number of columns: {num_cols}")
        print(f"[DEBUG] Template width: {self.template.width_mm}mm")
        print(f"[DEBUG] Margins (L,T,R,B): {ml}, {mt}, {mr}, {mb} mm")
        print(f"[DEBUG] PX_PER_MM: {PX_PER_MM}")
        # ========== DEBUG OUTPUT END ==========
        
        # Calculate column positions
        printable_width = self.template.width_mm - ml - mr
        start_x = ml * self.template.px_per_mm
        
        # ========== DEBUG OUTPUT START ==========
        print(f"[DEBUG] Printable width: {printable_width}mm")
        print(f"[DEBUG] Start X: {start_x}px")
        # ========== DEBUG OUTPUT END ==========
        
        guide_positions = []
        
        if mode == "Equal width":
            # Equal width columns
            col_width = printable_width / num_cols
            
            # ========== DEBUG OUTPUT START ==========
            print(f"[DEBUG] Equal width mode - Column width: {col_width}mm")
            # ========== DEBUG OUTPUT END ==========
            
            for i in range(num_cols + 1):
                x = start_x + (i * col_width * self.template.px_per_mm)
                guide = GuideLineItem(x, 0, x, self.template.height_px)
                self.scene.addItem(guide)
                self._column_guides.append(guide)
                guide_positions.append(x)
                
                # ========== DEBUG OUTPUT START ==========
                print(f"[DEBUG] Guide {i}: x={x:.2f}px")
                # ========== DEBUG OUTPUT END ==========
        else:
            # Custom width columns
            col_width_px = custom_width_mm * self.template.px_per_mm
            x = start_x
            guide_positions.append(x)
            
            # ========== DEBUG OUTPUT START ==========
            print(f"[DEBUG] Custom width mode - Column width: {custom_width_mm}mm ({col_width_px:.2f}px)")
            print(f"[DEBUG] Guide 0: x={x:.2f}px (left margin)")
            # ========== DEBUG OUTPUT END ==========
            
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
                    
                    # ========== DEBUG OUTPUT START ==========
                    print(f"[DEBUG] Guide {i+1}: x={x:.2f}px")
                    # ========== DEBUG OUTPUT END ==========
                else:
                    # ========== DEBUG OUTPUT START ==========
                    print(f"[DEBUG] Guide {i+1} skipped: x={x:.2f}px exceeds right margin")
                    # ========== DEBUG OUTPUT END ==========
        
        # Store positions in scene for itemChange() to access
        self.scene.column_guide_positions = guide_positions
        
        # ========== DEBUG OUTPUT START ==========
        print(f"[DEBUG] Total guides created: {len(self._column_guides)}")
        print(f"[DEBUG] Stored {len(guide_positions)} positions in scene.column_guide_positions")
        print(f"[DEBUG] Positions: {[f'{p:.2f}px' for p in guide_positions]}")
        print(f"[DEBUG] scene.column_guide_positions = {getattr(self.scene, 'column_guide_positions', 'NOT SET!')}")
        print(f"[DEBUG] Column guides setup complete\n")
        # ========== DEBUG OUTPUT END ==========
        
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

        try:
            factor = float(PX_PER_MM) if PX_PER_MM else 1.0
        except Exception:
            factor = 1.0

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
        """
        Snap selected items' Y to a baseline grid.

        Uses sb_baseline_mm, and aligns relative to:
        - top margin if "align to margins" is on
        - page top if it's off

        Locked items (data(0) == 'locked') are not moved.
        """
        from .items import GItem

        items = [
            it
            for it in self.scene.selectedItems()
            if isinstance(it, GItem) and it.data(0) != "locked"
        ]
        if not items:
            return

        step_mm = float(self.sb_baseline_mm.value())
        if step_mm <= 0:
            return

        try:
            factor = float(PX_PER_MM) if PX_PER_MM else 1.0
        except Exception:
            factor = 1.0

        step_px = step_mm * factor

        margins_mm = getattr(self.scene, "margins_mm", (0.0, 0.0, 0.0, 0.0))
        try:
            ml, mt, mr, mb = margins_mm
        except Exception:
            ml = mt = mr = mb = 0.0

        use_margins = getattr(self, "act_align_use_margins", None)
        use_margins = bool(use_margins and self.act_align_use_margins.isChecked())

        origin_y = mt * factor if use_margins else 0.0

        for it in items:
            pos = it.pos()
            x = pos.x()
            y = pos.y()

            if step_px <= 0:
                continue

            k = round((y - origin_y) / step_px)
            new_y = origin_y + k * step_px

            it.setPos(x, new_y)
            if hasattr(it, "elem"):
                try:
                    it.elem.x = float(x)
                    it.elem.y = float(new_y)
                except Exception:
                    pass

    def _delete_selected_items(self):
        """
        Delete selected items via DeleteItemCmd so it's undoable.
        """
        from .items import GItem, GLineItem, GRectItem, GEllipseItem, GStarItem

        sel = self.scene.selectedItems()
        if not sel:
            return

        items = [
            it
            for it in sel
            if isinstance(
                it,
                (
                    GItem,
                    GLineItem,
                    GRectItem,
                    GEllipseItem,
                    GStarItem,
                    GDiamondItem,
                    QtWidgets.QGraphicsItemGroup,
                ),
            )
        ]

        if not items:
            return

        cmd = DeleteItemCmd(self.scene, items, text="Delete item(s)")
        self.undo_stack.push(cmd)
        self._refresh_layers_safe()

    def _clear_column_guides(self):
        """Remove all column guides"""
        for guide in self._column_guides:
            self.scene.removeItem(guide)
        self._column_guides.clear()
        
        # *** CRITICAL: Clear positions from scene ***
        self.scene.column_guide_positions = []
        
        self.statusBar().showMessage("Cleared column guides", 2000)

    def _apply_preset(self, name: str) -> None:
        """
        Apply a layout preset by name: clears scene and creates elements.
        """
        if name == "fortune_cookie":
            if self._maybe_refresh_fortune_cookie():
                return
            
        from .items import GItem
        from ..core.models import Element

        # Base size for most presets
        if name in (
            "simple_store_receipt",
            "kitchen_ticket",
            "detailed_store_receipt",
            "pickup_ticket",
            "todo_checklist",
            "message_note",
            "fortune_cookie",
        ):
            self.template.width_mm = 80.0
            self.template.height_mm = 75.0
            self.update_paper()

        # Clear scene
        self.scene.clear()
        elems: list[Element] = []

        # ---- margin-aware geometry ----
        w_px = float(self.template.width_px)

        # Use the same margins tuple that update_paper / RulerView uses
        margins_mm = getattr(self.scene, "margins_mm", getattr(self.template, "margins_mm", (0.0, 0.0, 0.0, 0.0)))
        try:
            ml, mt, mr, mb = margins_mm
        except Exception:
            ml = mt = mr = mb = 0.0

        try:
            factor = float(PX_PER_MM) if PX_PER_MM else 1.0
        except Exception:
            factor = 1.0

        margin_left_px = ml * factor
        margin_right_px = mr * factor

        inner_pad = 1.0  # keep shapes off the red line by 1 px
        content_x = margin_left_px + inner_pad
        content_w = max(10.0, w_px - margin_left_px - margin_right_px - 2 * inner_pad)

        # ---------- Existing presets ----------
        if name == "simple_store_receipt":

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=5.0,
                    w=content_w,
                    h=30.0,
                    text="STORE NAME",
                    font_family="Arial",
                    font_size=16,
                    bold=True,
                    halign="center",
                    valign="top",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=40.0,
                    w=content_w,
                    h=40.0,
                    text="Address line 1\nCity, ST ZIP",
                    font_size=10,
                    halign="center",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=90.0,
                    w=content_w,
                    h=20.0,
                    text="Item         Qty     Price",
                    font_size=10,
                    bold=True,
                    halign="left",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=115.0,
                    w=content_w,
                    h=60.0,
                    text="Item 1\nItem 2\nItem 3",
                    font_size=10,
                    wrap=True,
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=185.0,
                    w=content_w,
                    h=20.0,
                    text="TOTAL: $0.00",
                    font_size=12,
                    bold=True,
                    halign="right",
                )
            )

        elif name == "kitchen_ticket":

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=5.0,
                    w=content_w,
                    h=30.0,
                    text="KITCHEN TICKET",
                    font_size=16,
                    bold=True,
                    halign="center",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=40.0,
                    w=content_w,
                    h=40.0,
                    text="Table: 00   Guests: 0\nServer: Name",
                    font_size=11,
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=90.0,
                    w=content_w,
                    h=90.0,
                    text="- 1x Item A\n- 2x Item B\n- 1x Item C",
                    font_size=12,
                    bold=True,
                    wrap=True,
                )
            )

        elif name == "detailed_store_receipt":

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=5.0,
                    w=content_w,
                    h=28.0,
                    text="STORE NAME",
                    font_family="Arial",
                    font_size=16,
                    bold=True,
                    halign="center",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=35.0,
                    w=content_w,
                    h=40.0,
                    text="123 Main St\nCity, ST 12345\n(000) 000-0000",
                    font_size=9,
                    halign="center",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=80.0,
                    w=content_w,
                    h=24.0,
                    text="Date: 2025-01-01   Time: 12:34\nTicket: 000123",
                    font_size=9,
                    halign="left",
                    wrap=True,
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=110.0,
                    w=content_w,
                    h=16.0,
                    text="------------------------------",
                    font_size=9,
                    halign="center",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=130.0,
                    w=content_w,
                    h=18.0,
                    text="Item           Qty    Price    Total",
                    font_size=9,
                    bold=True,
                    halign="left",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=150.0,
                    w=content_w,
                    h=80.0,
                    text=(
                        "Item A         1      5.00     5.00\n"
                        "Item B         2      3.50     7.00\n"
                        "Item C         1      2.99     2.99"
                    ),
                    font_size=9,
                    wrap=True,
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=235.0,
                    w=content_w,
                    h=50.0,
                    text=(
                        "Subtotal:        $14.99\n"
                        "Tax (6.0%):      $0.90\n"
                        "TOTAL:           $15.89"
                    ),
                    font_size=10,
                    bold=False,
                    halign="right",
                    wrap=True,
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=290.0,
                    w=content_w,
                    h=30.0,
                    text="Paid with: VISA •••• 1234",
                    font_size=9,
                    halign="right",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=325.0,
                    w=content_w,
                    h=40.0,
                    text="Thank you for your business!\nNo returns without receipt.",
                    font_size=9,
                    halign="center",
                    wrap=True,
                )
            )

        elif name == "pickup_ticket":

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=10.0,
                    w=content_w,
                    h=50.0,
                    text="ORDER #1234",
                    font_size=24,
                    bold=True,
                    halign="center",
                    valign="top",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=65.0,
                    w=content_w,
                    h=30.0,
                    text="Customer: JOHN DOE",
                    font_size=12,
                    bold=True,
                    halign="center",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=105.0,
                    w=content_w,
                    h=80.0,
                    text="- 1x Burger w/ Fries\n- 2x Soda\n- 1x Dessert",
                    font_size=12,
                    bold=True,
                    wrap=True,
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=195.0,
                    w=content_w,
                    h=40.0,
                    text="Pickup: 12:30 PM\nOrder type: Takeout",
                    font_size=11,
                    wrap=True,
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=240.0,
                    w=content_w,
                    h=30.0,
                    text="Queue position: 5",
                    font_size=12,
                    bold=True,
                    halign="center",
                )
            )

        elif name == "todo_checklist":

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=5.0,
                    w=content_w,
                    h=26.0,
                    text="TO-DO / CHECKLIST",
                    font_size=16,
                    bold=True,
                    halign="center",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=35.0,
                    w=content_w,
                    h=18.0,
                    text="Date: ____________________",
                    font_size=11,
                    halign="left",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=60.0,
                    w=content_w,
                    h=120.0,
                    text=(
                        "[ ] Item 1\n"
                        "[ ] Item 2\n"
                        "[ ] Item 3\n"
                        "[ ] Item 4\n"
                        "[ ] Item 5"
                    ),
                    font_size=12,
                    wrap=True,
                )
            )

        elif name == "message_note":

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=5.0,
                    w=content_w,
                    h=26.0,
                    text="MESSAGE NOTE",
                    font_size=16,
                    bold=True,
                    halign="center",
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=35.0,
                    w=content_w,
                    h=70.0,
                    text=(
                        "For:   ______________________\n"
                        "From:  ______________________\n"
                        "Phone: ______________________\n"
                        "Date:  ______   Time: ______"
                    ),
                    font_size=11,
                    wrap=True,
                )
            )

            elems.append(
                Element(
                    kind="text",
                    x=content_x,
                    y=110.0,
                    w=content_w,
                    h=110.0,
                    text=(
                        "Message:\n"
                        "____________________________\n"
                        "____________________________\n"
                        "____________________________"
                    ),
                    font_size=11,
                    wrap=True,
                )
            )

        # ---------- Fortune cookie slip (styled) ----------
        elif name == "fortune_cookie":
            # Get fortune + lucky numbers from helper
            fortune_text, lucky_raw = self._get_random_fortune()

            # Reformat numbers: "26, 49, 94, 31, 63, 49" -> "26  49  94  31  63  49"
            parts = [p.strip() for p in lucky_raw.replace(",", " ").split() if p.strip()]
            if parts:
                lucky_line = "  ".join(parts)
            else:
                lucky_line = lucky_raw

            # 1) Header – big, bold, sans
            header = Element(
                kind="text",
                x=content_x,
                y=5.0,
                w=content_w,
                h=30.0,
                text="FORTUNE COOKIE",
                font_family="Arial",
                font_size=45,
                bold=True,
                halign="center",
            )
            header.template_id = "fortune_cookie"
            header.slot = "header"
            elems.append(header)

            # 2) Divider line – fake it with underscores so it survives printers/fonts
            divider = Element(
                kind="text",
                x=content_x,
                y=38.0,
                w=content_w,
                h=10.0,
                text="____________________________",
                font_family="Arial",
                font_size=10,
                halign="center",
            )
            divider.template_id = "fortune_cookie"
            divider.slot = "divider"
            elems.append(divider)

            # 3) Fortune body – big serif, centered, wrapped
            body = Element(
                kind="text",
                x=content_x,
                y=60.0,
                w=content_w,
                h=90.0,
                text=fortune_text,
                font_family="Constantia",   # or "Georgia"
                font_size=33,
                bold=True,
                halign="center",
                wrap=True,
            )
            body.template_id = "fortune_cookie"
            body.slot = "body"
            elems.append(body)

            # 4) Lucky numbers – monospace, two-line like your mock
            lucky = Element(
                kind="text",
                x=content_x,
                y=155.0,
                w=content_w,
                h=40.0,
                text=f"Lucky numbers:\n{lucky_line}",
                font_family="Lucida Console",
                font_size=27,
                bold=True,
                halign="center",
                wrap=True,
            )
            lucky.template_id = "fortune_cookie"
            lucky.slot = "lucky"
            elems.append(lucky)


        else:
            return

        # Add items to scene
        for e in elems:
            item = GItem(e)
            item.undo_stack = self.undo_stack
            item._main_window = self
            self.scene.addItem(item)
            item.setPos(e.x, e.y)

        self._refresh_layers_safe()
        self.statusBar().showMessage(f"Applied preset: {name}", 3000)





    def _hide_selected(self):
        """
        Hide selected items.
        """
        for it in self.scene.selectedItems():
            it.setVisible(False)
            it.setData(1, "hidden_by_tool")

    def _show_all_hidden(self):
        """
        Show all items previously hidden by _hide_selected.
        """
        for it in self.scene.items():
            if it.data(1) == "hidden_by_tool":
                it.setVisible(True)

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
        dlg = QtWidgets.QDialog(self)
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
                    # Shortcut column → slight bold
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
