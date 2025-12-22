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

# -------------------------
# App constants / QSettings
# -------------------------
ORG_NAME = "ByteSized Labs"
APP_NAME = "Receipt Lab"
APP_VERSION = "0.9.0"

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
        self._snap_guard = False

        # Layer refresh re-entrancy guard
        self._layer_refreshing = False

        self._build_scene_view()
        self._build_toolbars_menus()
        self._build_docks()

        self.update_paper()
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

    def _build_toolbars_menus(self):
        # ---- Undo/Redo ----
        act_undo = self.undo_stack.createUndoAction(self, "Undo")
        act_undo.setShortcut(QtGui.QKeySequence.Undo)
        act_redo = self.undo_stack.createRedoAction(self, "Redo")
        act_redo.setShortcut(QtGui.QKeySequence.Redo)

        # =============================
        # Main toolbar: file/print/printer/page
        # =============================
        tb_main = QtWidgets.QToolBar("Main")
        tb_main.setIconSize(QtCore.QSize(16, 16))
        self.addToolBar(tb_main)

        # File (quick save/load current template)
        act_save = QtGui.QAction("Save", self)
        act_save.triggered.connect(self.save_template)
        tb_main.addAction(act_save)

        act_load = QtGui.QAction("Load", self)
        act_load.triggered.connect(self.load_template)
        tb_main.addAction(act_load)

        tb_main.addSeparator()

        # Print / Config
        act_print = QtGui.QAction("Print", self)
        act_print.triggered.connect(self.print_now)
        tb_main.addAction(act_print)

        act_conf = QtGui.QAction("Config", self)
        act_conf.triggered.connect(self.configure_printer)
        tb_main.addAction(act_conf)

        tb_main.addSeparator()

        # Transport
        act_feed = QtGui.QAction("Feed", self)
        act_feed.triggered.connect(lambda: self.quick_action("feed"))
        tb_main.addAction(act_feed)

        act_cut_btn = QtGui.QAction("Cut", self)
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
        tb_main.addWidget(self.sb_darkness)

        tb_main.addSeparator()
        tb_main.addWidget(QtWidgets.QLabel("Cut:"))

        self.cb_cut = QtWidgets.QComboBox()
        self.cb_cut.addItems(["Full", "Partial", "None"])
        _cut_saved = (self.printer_cfg.get("cut_mode", "partial") or "partial").lower()
        _cut_map = {"full": "Full", "partial": "Partial", "none": "None"}
        self.cb_cut.setCurrentText(_cut_map.get(_cut_saved, "Partial"))
        self.cb_cut.currentTextChanged.connect(self._on_cut_changed)
        tb_main.addWidget(self.cb_cut)

        # ---- Printer profile selector ----
        tb_main.addSeparator()
        tb_main.addWidget(QtWidgets.QLabel("Profile:"))

        self.profile_combo = QtWidgets.QComboBox()
        self.profile_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self._refresh_profile_combo()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        tb_main.addWidget(self.profile_combo)

        # ---- Page size controls ----
        tb_main.addSeparator()
        tb_main.addWidget(QtWidgets.QLabel("Width:"))
        self.cb_w_mm = QtWidgets.QComboBox()
        self.cb_w_mm.setEditable(True)
        self.cb_w_mm.addItems(["58 mm", "80 mm", "100 mm"])
        self.cb_w_mm.setCurrentText(f"{int(self.template.width_mm)} mm")
        tb_main.addWidget(self.cb_w_mm)

        tb_main.addWidget(QtWidgets.QLabel("Height:"))
        self.cb_h_mm = QtWidgets.QComboBox()
        self.cb_h_mm.setEditable(True)
        self.cb_h_mm.addItems(["50 mm", "75 mm", "200 mm", "300 mm"])
        self.cb_h_mm.setCurrentText(f"{int(self.template.height_mm)} mm")
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
            "When checked: align relative to printable margins.\n"
            "When unchecked: align relative to full page."
        )
        tb_layout.addAction(self.act_align_use_margins)

        act_align_left = QtGui.QAction("⟵", self)
        act_align_left.setToolTip("Align Left")
        act_align_left.triggered.connect(lambda: self._align_selected("left"))
        tb_layout.addAction(act_align_left)

        act_align_hcenter = QtGui.QAction("↔", self)
        act_align_hcenter.setToolTip("Align Horizontal Center")
        act_align_hcenter.triggered.connect(lambda: self._align_selected("hcenter"))
        tb_layout.addAction(act_align_hcenter)

        act_align_right = QtGui.QAction("⟶", self)
        act_align_right.setToolTip("Align Right")
        act_align_right.triggered.connect(lambda: self._align_selected("right"))
        tb_layout.addAction(act_align_right)

        tb_layout.addSeparator()

        act_align_top = QtGui.QAction("⟰", self)
        act_align_top.setToolTip("Align Top")
        act_align_top.triggered.connect(lambda: self._align_selected("top"))
        tb_layout.addAction(act_align_top)

        act_align_vcenter = QtGui.QAction("↕", self)
        act_align_vcenter.setToolTip("Align Vertical Middle")
        act_align_vcenter.triggered.connect(lambda: self._align_selected("vcenter"))
        tb_layout.addAction(act_align_vcenter)

        act_align_bottom = QtGui.QAction("⟱", self)
        act_align_bottom.setToolTip("Align Bottom")
        act_align_bottom.triggered.connect(lambda: self._align_selected("bottom"))
        tb_layout.addAction(act_align_bottom)

        # ---- Distribute ----
        tb_layout.addSeparator()
        tb_layout.addWidget(QtWidgets.QLabel("Distrib:"))

        act_dist_h = QtGui.QAction("H", self)
        act_dist_h.setToolTip("Distribute Horizontally (centers)")
        act_dist_h.triggered.connect(lambda: self._distribute_selected("h"))
        tb_layout.addAction(act_dist_h)

        act_dist_v = QtGui.QAction("V", self)
        act_dist_v.setToolTip("Distribute Vertically (centers)")
        act_dist_v.triggered.connect(lambda: self._distribute_selected("v"))
        tb_layout.addAction(act_dist_v)

        # ---- Group / Ungroup ----
        tb_layout.addSeparator()
        tb_layout.addWidget(QtWidgets.QLabel("Group:"))

        act_group = QtGui.QAction("Grp", self)
        act_group.setToolTip("Group selected items (Ctrl+G)")
        act_group.setShortcut("Ctrl+G")
        act_group.triggered.connect(self._group_selected)
        tb_layout.addAction(act_group)

        act_ungroup = QtGui.QAction("Ungrp", self)
        act_ungroup.setToolTip("Ungroup selected groups (Ctrl+Shift+G)")
        act_ungroup.setShortcut("Ctrl+Shift+G")
        act_ungroup.triggered.connect(self._ungroup_selected)
        tb_layout.addAction(act_ungroup)

        # ---- Z-order ----
        tb_layout.addSeparator()
        tb_layout.addWidget(QtWidgets.QLabel("Order:"))

        # Bring to front
        act_front = QtGui.QAction("Front", self)
        act_front.setToolTip("Bring selected item to the very front")
        act_front.triggered.connect(lambda: self._change_z_order("front"))
        tb_layout.addAction(act_front)

        # Send to back
        act_back = QtGui.QAction("Back", self)
        act_back.setToolTip("Send selected item to the very back")
        act_back.triggered.connect(lambda: self._change_z_order("back"))
        tb_layout.addAction(act_back)

        # One step forward
        act_up = QtGui.QAction("Raise", self)
        act_up.setToolTip("Move selected item one step forward")
        act_up.triggered.connect(lambda: self._change_z_order("up"))
        tb_layout.addAction(act_up)

        # One step backward
        act_down = QtGui.QAction("Lower", self)
        act_down.setToolTip("Move selected item one step backward")
        act_down.triggered.connect(lambda: self._change_z_order("down"))
        tb_layout.addAction(act_down)

        # ---- Lock / Hide ----
        tb_layout.addSeparator()
        tb_layout.addWidget(QtWidgets.QLabel("Lock:"))

        act_lock = QtGui.QAction("Lock", self)
        act_lock.setToolTip("Lock selected items (prevent moving/resizing)")
        act_lock.triggered.connect(self._lock_selected)
        tb_layout.addAction(act_lock)

        act_unlock = QtGui.QAction("Unlock", self)
        act_unlock.setToolTip("Unlock selected items")
        act_unlock.triggered.connect(self._unlock_selected)
        tb_layout.addAction(act_unlock)

        act_hide = QtGui.QAction("Hide", self)
        act_hide.setToolTip("Hide selected items")
        act_hide.triggered.connect(self._hide_selected)
        tb_layout.addAction(act_hide)

        act_show_all = QtGui.QAction("Unhide", self)
        act_show_all.setToolTip("Show all hidden items")
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
        tb_layout.addWidget(self.sb_baseline_mm)

        act_baseline_apply = QtGui.QAction("Apply", self)
        act_baseline_apply.setToolTip("Snap selected items' Y to baseline grid")
        act_baseline_apply.triggered.connect(self._apply_baseline_to_selected)
        tb_layout.addAction(act_baseline_apply)

        # Shortcut: Delete selected items
        self._shortcut_delete = QtGui.QShortcut(QtGui.QKeySequence.Delete, self)
        self._shortcut_delete.activated.connect(self._delete_selected_items)

        # =============================
        # Menubar
        # =============================
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu("&File")

        act_open = QtGui.QAction("Open Template…", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self.load_template)
        file_menu.addAction(act_open)

        act_save = QtGui.QAction("Save Template…", self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self.save_template)
        file_menu.addAction(act_save)

        file_menu.addSeparator()

        act_export_png = QtGui.QAction("Export as PNG…", self)
        act_export_png.triggered.connect(self.export_png)
        file_menu.addAction(act_export_png)

        act_export_pdf = QtGui.QAction("Export as PDF…", self)
        act_export_pdf.triggered.connect(self.export_pdf)
        file_menu.addAction(act_export_pdf)

        file_menu.addSeparator()

        act_file_print = QtGui.QAction("Print…", self)
        act_file_print.setShortcut("Ctrl+P")
        act_file_print.triggered.connect(self.print_now)
        file_menu.addAction(act_file_print)

        file_menu.addSeparator()

        act_exit = QtGui.QAction("Exit", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # View
        self.action_margins = QtGui.QAction("Show Printable Margins", self)
        self.action_margins.setCheckable(True)
        self.action_margins.setChecked(True)
        self.action_margins.setShortcut("Ctrl+M")
        self.action_margins.toggled.connect(self._on_toggle_margins)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.action_margins)

        # Insert
        insert_menu = menubar.addMenu("&Insert")

        # Text
        act_add_text = QtGui.QAction("Text", self)
        act_add_text.setShortcut("Ctrl+Shift+T")
        act_add_text.triggered.connect(self.add_text)
        insert_menu.addAction(act_add_text)

        # Barcode
        act_add_barcode = QtGui.QAction("Barcode", self)
        act_add_barcode.setShortcut("Ctrl+Shift+B")
        act_add_barcode.triggered.connect(self.add_barcode)
        insert_menu.addAction(act_add_barcode)

        insert_menu.addSeparator()

        # Image
        act_add_image = QtGui.QAction("Image…", self)
        act_add_image.setShortcut("Ctrl+Shift+I")
        act_add_image.triggered.connect(self.add_image)
        insert_menu.addAction(act_add_image)

        insert_menu.addSeparator()


        # Line
        act_add_line = QtGui.QAction("Line", self)
        act_add_line.setShortcut("Ctrl+Shift+L")
        act_add_line.triggered.connect(self.add_line)
        insert_menu.addAction(act_add_line)

        # Shapes if available
        if hasattr(self, "add_rect"):
            act_add_rect = QtGui.QAction("Rectangle", self)
            act_add_rect.setShortcut("Ctrl+Shift+R")
            act_add_rect.triggered.connect(self.add_rect)
            insert_menu.addAction(act_add_rect)

        if hasattr(self, "add_circle"):
            act_add_circle = QtGui.QAction("Circle", self)
            act_add_circle.setShortcut("Ctrl+Shift+C")
            act_add_circle.triggered.connect(self.add_circle)
            insert_menu.addAction(act_add_circle)

        if hasattr(self, "add_star"):
            act_add_star = QtGui.QAction("Star", self)
            act_add_star.setShortcut("Ctrl+Shift+S")
            act_add_star.triggered.connect(self.add_star)
            insert_menu.addAction(act_add_star)

        if hasattr(self, "add_arrow"):
            act_add_arrow = QtGui.QAction("Arrow", self)
            act_add_arrow.setShortcut("Ctrl+Shift+A")
            act_add_arrow.triggered.connect(self.add_arrow)
            insert_menu.addAction(act_add_arrow)

        if hasattr(self, "add_diamond"):
            act_add_diamond = QtGui.QAction("Diamond", self)
            act_add_diamond.setShortcut("Ctrl+Shift+D")
            act_add_diamond.triggered.connect(self.add_diamond)
            insert_menu.addAction(act_add_diamond)

        # Layout menu (column guides, baseline, presets)
        layout_menu = menubar.addMenu("&Layout")

        act_cols = QtGui.QAction("Set Column Guides…", self)
        act_cols.triggered.connect(self._set_column_guides_dialog)
        layout_menu.addAction(act_cols)

        act_cols_clear = QtGui.QAction("Clear Column Guides", self)
        act_cols_clear.triggered.connect(self._clear_column_guides)
        layout_menu.addAction(act_cols_clear)

        layout_menu.addSeparator()

        act_baseline_menu = QtGui.QAction("Apply Baseline to Selection", self)
        act_baseline_menu.triggered.connect(self._apply_baseline_to_selected)
        layout_menu.addAction(act_baseline_menu)

        presets_menu = layout_menu.addMenu("Presets")

        act_preset_simple = QtGui.QAction("Simple Store Receipt", self)
        act_preset_simple.triggered.connect(
            lambda: self._apply_preset("simple_store_receipt")
        )
        presets_menu.addAction(act_preset_simple)

        act_preset_kitchen = QtGui.QAction("Kitchen Ticket", self)
        act_preset_kitchen.triggered.connect(
            lambda: self._apply_preset("kitchen_ticket")
        )
        presets_menu.addAction(act_preset_kitchen)

        # --- New presets ---

        act_preset_detailed = QtGui.QAction("Detailed Store Receipt", self)
        act_preset_detailed.triggered.connect(
            lambda: self._apply_preset("detailed_store_receipt")
        )
        presets_menu.addAction(act_preset_detailed)

        act_preset_pickup = QtGui.QAction("Pickup Ticket", self)
        act_preset_pickup.triggered.connect(
            lambda: self._apply_preset("pickup_ticket")
        )
        presets_menu.addAction(act_preset_pickup)

        act_preset_todo = QtGui.QAction("To-Do / Checklist", self)
        act_preset_todo.triggered.connect(
            lambda: self._apply_preset("todo_checklist")
        )
        presets_menu.addAction(act_preset_todo)

        act_preset_message = QtGui.QAction("Message Note", self)
        act_preset_message.triggered.connect(
            lambda: self._apply_preset("message_note")
        )
        presets_menu.addAction(act_preset_message)

        act_preset_fortune = QtGui.QAction("Fortune Cookie", self)
        act_preset_fortune.triggered.connect(
            lambda: self._apply_preset("fortune_cookie")
        )
        presets_menu.addAction(act_preset_fortune)



        # =============================
        # Help menu
        # =============================
        help_menu = menubar.addMenu("&Help")

        act_shortcuts = QtGui.QAction("Keyboard Shortcuts…", self)
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

        # Share the right side
        self.tabifyDockWidget(dock_layers, dock_props)
        dock_props.raise_()

        # Keep panels in sync
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.scene.changed.connect(self._on_scene_changed)
        self.props.element_changed.connect(self._on_props_element_changed)
        # self.props.element_changed.connect(lambda *_: self._refresh_layers_safe())


    # -------------------------
    # Theme & paper
    # -------------------------
    def apply_theme(self):
        # keep it neutral; you can swap in dark later
        self.setStyleSheet("")

    def update_paper(self):
        # set scene rect from Template
        w = float(self.template.width_px)
        h = float(self.template.height_px)
        self.scene.setSceneRect(0, 0, w, h)

        # expose properties that RulerView expects
        self.scene.setProperty("paper_width", w)
        self.scene.setProperty("paper_height", h)

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
        # Pick file
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.svg);;All files (*.*)",
        )
        if not path:
            return

        path = os.path.abspath(path)

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
        elem.image_path = path

        item = GItem(elem)
        item.undo_stack = self.undo_stack
        item.setPos(x_px, y_px)

        self.scene.addItem(item)
        self.template.elements.append(elem)

        # select it
        self.scene.clearSelection()
        item.setSelected(True)

        # keep UI in sync
        self._refresh_layers_safe()
        self._on_selection_changed()


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
        img = scene_to_image(self.scene, scale=1.0)

        if img is None or img.isNull():
            QtWidgets.QMessageBox.warning(
                self, "Print error", "Could not render the scene to an image."
            )
            print("[PRINT DEBUG] scene_to_image returned null image")
            return

        print(
            "[PRINT DEBUG] scene_to_image returned:",
            img.width(),
            "x",
            img.height(),
        )

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
            QtWidgets.QMessageBox.warning(self, "Print error", err)

        worker.signals.finished.connect(_on_finished)
        worker.signals.error.connect(_on_error)
        worker.start()

    def export_png(self):
        """
        Render the current scene to a PNG image file.
        """
        img = scene_to_image(self.scene, scale=1.0)

        if img is None or img.isNull():
            QtWidgets.QMessageBox.warning(
                self, "Export error", "Could not render the scene to an image."
            )
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export as PNG", "", "PNG Images (*.png)"
        )
        if not path:
            return

        ok = img.save(path, "PNG")
        if not ok:
            QtWidgets.QMessageBox.warning(
                self, "Export error", "Failed to save PNG image."
            )
            return

        self.statusBar().showMessage(f"Exported PNG: {path}", 3000)

    def export_pdf(self):
        """
        Render the current scene to a single-page PDF file.
        """
        img = scene_to_image(self.scene, scale=1.0)

        if img is None or img.isNull():
            QtWidgets.QMessageBox.warning(
                self, "Export error", "Could not render the scene to an image."
            )
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export as PDF", "", "PDF Files (*.pdf)"
        )
        if not path:
            return

        writer = QtGui.QPdfWriter(path)
        try:
            writer.setResolution(self.template.dpi)
            writer.setPageSizeMM(
                QtCore.QSizeF(self.template.width_mm, self.template.height_mm)
            )
        except Exception:
            # If template is missing for some reason, just let Qt pick defaults
            pass

        painter = QtGui.QPainter(writer)
        if not painter.isActive():
            QtWidgets.QMessageBox.warning(
                self, "Export error", "Could not open PDF for writing."
            )
            return

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
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Template", "", "Template JSON (*.json)"
        )
        if not path:
            return
        elements = []
        for it in self.scene.items():
            if isinstance(it, GItem):
                elements.append(it.elem.to_dict())
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
        )
        with open(path, "w", encoding="utf-8") as f:
            json.dump(t.to_dict(), f, indent=2)
        self.statusBar().showMessage(f"Saved: {path}", 3000)

    def load_template(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Template", "", "Template JSON (*.json)"
        )
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.template = Template.from_dict(data)

        self.scene.clear()
        for e in self.template.elements:
            item = GItem(e)
            item.undo_stack = self.undo_stack
            self.scene.addItem(item)
            item.setPos(e.x, e.y)

        self.update_paper()
        self._refresh_layers_safe()
        self.statusBar().showMessage(f"Loaded: {path}", 3000)

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
        Load printer profiles from QSettings.

        If no profiles JSON is present, migrate from the legacy single
        printer config (load_printer_settings) into a 'Default' profile.
        """
        s = self.settings
        raw = s.value("printer/profiles_json", "", type=str)

        profiles: list[dict] = []
        if raw:
            try:
                arr = json.loads(raw)
                for d in arr:
                    name = d.get("name") or "Unnamed"
                    cfg = d.get("config") or {}
                    profiles.append({"name": name, "config": cfg})
            except Exception:
                profiles = []

        if not profiles:
            # First run / migration path: wrap existing single config
            cfg = self.load_printer_settings()
            name = cfg.get("profile") or "Default"
            profiles = [{"name": name, "config": cfg}]

            try:
                s.setValue("printer/profiles_json", json.dumps(profiles, indent=2))
            except Exception:
                pass

        self.profiles: list[dict] = profiles
        self.current_profile_index: int = 0
        # Active config is a copy so we can tweak it in-memory
        self.printer_cfg: dict = dict(self.profiles[0]["config"])

    def _save_printer_profiles(self) -> None:
        """
        Persist all printer profiles to QSettings as JSON.
        """
        if not hasattr(self, "profiles"):
            return

        s = self.settings
        try:
            raw = json.dumps(self.profiles, indent=2)
            s.setValue("printer/profiles_json", raw)
        except Exception:
            # Don't crash the app just because JSON failed
            pass

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
                new_elem.x = float(getattr(it.elem, "x", 0.0)) + 5.0
                new_elem.y = float(getattr(it.elem, "y", 0.0)) + 5.0
                new_item = GItem(new_elem)
                self.scene.addItem(new_item)
                new_item.setPos(new_elem.x, new_elem.y)
                new_items.append(new_item)

        if new_items:
            self.scene.clearSelection()
            for ni in new_items:
                ni.setSelected(True)
            self._refresh_layers_safe()

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
        """
        Prompt for X positions (mm) and create vertical column guides.
        """
        text, ok = QtWidgets.QInputDialog.getText(
            self,
            "Set Column Guides",
            "Enter X positions in mm (comma-separated):",
        )
        if not ok or not text.strip():
            return

        parts = [p.strip() for p in text.split(",") if p.strip()]
        mm_values = []
        for p in parts:
            try:
                mm_values.append(float(p))
            except ValueError:
                pass

        if not mm_values:
            return

        self._set_column_guides(mm_values)

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
        if not hasattr(self, "_column_guides"):
            return
        for g in self._column_guides:
            self.scene.removeItem(g)
        self._column_guides.clear()

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
