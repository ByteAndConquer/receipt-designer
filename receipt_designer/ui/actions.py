# receipt_designer/ui/actions.py
"""
Builder functions for QActions, menus, toolbars, and keyboard shortcuts.

All builders receive the MainWindow instance (or specific callbacks) to avoid
circular imports — this module must NOT import main_window_impl.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from .host_protocols import ActionsHost


def build_toolbars_and_menus(mw: ActionsHost) -> None:
    """
    Create all toolbars, menus, and keyboard shortcuts and attach them to *mw*.

    *mw* is expected to expose the same attributes/methods as MainWindow
    (undo_stack, printer_cfg, template, etc.).  This function sets several
    widget attributes on *mw* (sb_darkness, cb_cut, profile_combo, cb_w_mm,
    cb_h_mm, sb_baseline_mm, action_margins, action_dark_mode, recent_menu,
    act_align_use_margins, _shortcut_delete, _shortcut_duplicate).
    """

    # ---- Undo/Redo ----
    act_undo = mw.undo_stack.createUndoAction(mw, "Undo")
    act_undo.setShortcut(QtGui.QKeySequence.Undo)
    act_undo.setToolTip("Undo last action (Ctrl+Z)")

    act_redo = mw.undo_stack.createRedoAction(mw, "Redo")
    act_redo.setShortcut(QtGui.QKeySequence.Redo)
    act_redo.setToolTip("Redo previously undone action (Ctrl+Y or Ctrl+Shift+Z)")

    # =============================
    # Main toolbar: file/print/printer/page
    # =============================
    tb_main = QtWidgets.QToolBar("Main")
    tb_main.setIconSize(QtCore.QSize(16, 16))
    mw.addToolBar(tb_main)

    # File (quick save/load current template)
    act_save = QtGui.QAction("Save", mw)
    act_save.setToolTip("Save current template to file (Ctrl+S)")
    act_save.triggered.connect(mw.save_template)
    tb_main.addAction(act_save)

    act_load = QtGui.QAction("Load", mw)
    act_load.setToolTip("Open template from file (Ctrl+O)")
    act_load.triggered.connect(mw.load_template)
    tb_main.addAction(act_load)

    tb_main.addSeparator()

    act_preview = QtGui.QAction("Preview", mw)
    act_preview.setToolTip("Preview how the receipt will look before printing (Ctrl+Shift+P)")
    act_preview.triggered.connect(mw.preview_print)
    tb_main.addAction(act_preview)

    # Print / Config
    act_print = QtGui.QAction("Print", mw)
    act_print.setToolTip("Send template to thermal printer (Ctrl+P)")
    act_print.triggered.connect(mw.print_now)
    tb_main.addAction(act_print)

    act_conf = QtGui.QAction("Config", mw)
    act_conf.setToolTip("Configure printer connection and settings")
    act_conf.triggered.connect(mw.configure_printer)
    tb_main.addAction(act_conf)

    tb_main.addSeparator()

    # Transport
    act_feed = QtGui.QAction("Feed", mw)
    act_feed.setToolTip("Feed paper through printer without printing")
    act_feed.triggered.connect(lambda: mw.quick_action("feed"))
    tb_main.addAction(act_feed)

    act_cut_btn = QtGui.QAction("Cut", mw)
    act_cut_btn.setToolTip("Cut paper at current position")
    act_cut_btn.triggered.connect(lambda: mw.quick_action("cut"))
    tb_main.addAction(act_cut_btn)

    tb_main.addSeparator()
    tb_main.addAction(act_undo)
    tb_main.addAction(act_redo)

    # ---- Job settings: Darkness & Cut mode ----
    tb_main.addSeparator()
    tb_main.addWidget(QtWidgets.QLabel("Darkness:"))

    mw.sb_darkness = QtWidgets.QSpinBox()
    mw.sb_darkness.setRange(1, 255)
    mw.sb_darkness.setAccelerated(True)
    mw.sb_darkness.setValue(int(mw.printer_cfg.get("darkness", 180)))
    mw.sb_darkness.valueChanged.connect(mw._on_darkness_changed)
    mw.sb_darkness.setToolTip(
        "Print darkness level (1-255)\n"
        "Higher values = darker print\n"
        "Recommended: 150-200"
    )
    tb_main.addWidget(mw.sb_darkness)

    tb_main.addSeparator()
    tb_main.addWidget(QtWidgets.QLabel("Cut:"))

    mw.cb_cut = QtWidgets.QComboBox()
    mw.cb_cut.addItems(["Full", "Partial", "None"])
    _cut_saved = (mw.printer_cfg.get("cut_mode", "partial") or "partial").lower()
    _cut_map = {"full": "Full", "partial": "Partial", "none": "None"}
    mw.cb_cut.setCurrentText(_cut_map.get(_cut_saved, "Partial"))
    mw.cb_cut.currentTextChanged.connect(mw._on_cut_changed)
    mw.cb_cut.setToolTip(
        "Paper cutting mode:\n"
        "• Full: Complete cut through paper\n"
        "• Partial: Perforation for easy tearing\n"
        "• None: No cutting (continuous paper)"
    )
    tb_main.addWidget(mw.cb_cut)

    # ---- Printer profile selector ----
    tb_main.addSeparator()
    tb_main.addWidget(QtWidgets.QLabel("Profile:"))

    mw.profile_combo = QtWidgets.QComboBox()
    mw.profile_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
    mw._refresh_profile_combo()
    mw.profile_combo.currentIndexChanged.connect(mw._on_profile_changed)
    mw.profile_combo.setToolTip("Select saved printer profile")
    tb_main.addWidget(mw.profile_combo)

    # ---- Page size controls ----
    tb_main.addSeparator()
    tb_main.addWidget(QtWidgets.QLabel("Width:"))
    mw.cb_w_mm = QtWidgets.QComboBox()
    mw.cb_w_mm.setEditable(True)
    mw.cb_w_mm.addItems(["58 mm", "80 mm", "100 mm"])
    mw.cb_w_mm.setCurrentText(f"{int(mw.template.width_mm)} mm")
    mw.cb_w_mm.setToolTip("Paper width in millimeters (common: 58mm, 80mm)")
    tb_main.addWidget(mw.cb_w_mm)

    tb_main.addWidget(QtWidgets.QLabel("Height:"))
    mw.cb_h_mm = QtWidgets.QComboBox()
    mw.cb_h_mm.setEditable(True)
    mw.cb_h_mm.addItems(["50 mm", "75 mm", "200 mm", "300 mm"])
    mw.cb_h_mm.setCurrentText(f"{int(mw.template.height_mm)} mm")
    mw.cb_h_mm.setToolTip("Paper height in millimeters")
    tb_main.addWidget(mw.cb_h_mm)

    def _apply_page():
        def parse_mm(s: str) -> float:
            s = s.lower().strip().replace("mm", "").strip()
            return float(s) if s else 80.0

        mw.template.width_mm = parse_mm(mw.cb_w_mm.currentText())
        mw.template.height_mm = parse_mm(mw.cb_h_mm.currentText())
        mw.update_paper()

    mw.cb_w_mm.editTextChanged.connect(lambda *_: _apply_page())
    mw.cb_h_mm.editTextChanged.connect(lambda *_: _apply_page())
    mw.cb_w_mm.currentTextChanged.connect(lambda *_: _apply_page())
    mw.cb_h_mm.currentTextChanged.connect(lambda *_: _apply_page())

    # =============================
    # Layout toolbar: align / distrib / group / z / lock / baseline
    # =============================
    mw.addToolBarBreak()
    tb_layout = QtWidgets.QToolBar("Layout")
    tb_layout.setIconSize(QtCore.QSize(16, 16))
    mw.addToolBar(tb_layout)

    # ---- Align controls ----
    tb_layout.addWidget(QtWidgets.QLabel("Align:"))

    # Toggle: align to margins vs whole page
    mw.act_align_use_margins = QtGui.QAction("Margins", mw)
    mw.act_align_use_margins.setCheckable(True)
    mw.act_align_use_margins.setChecked(True)
    mw.act_align_use_margins.setToolTip(
        "Align to margins vs full page:\n"
        "• Checked: Align relative to printable area (respects margins)\n"
        "• Unchecked: Align relative to full page edges"
    )
    tb_layout.addAction(mw.act_align_use_margins)

    act_align_left = QtGui.QAction("⟵", mw)
    act_align_left.setToolTip("Align selected items to left edge")
    act_align_left.triggered.connect(lambda: mw._align_selected("left"))
    tb_layout.addAction(act_align_left)

    act_align_hcenter = QtGui.QAction("↔", mw)
    act_align_hcenter.setToolTip("Align selected items to horizontal center")
    act_align_hcenter.triggered.connect(lambda: mw._align_selected("hcenter"))
    tb_layout.addAction(act_align_hcenter)

    act_align_right = QtGui.QAction("⟶", mw)
    act_align_right.setToolTip("Align selected items to right edge")
    act_align_right.triggered.connect(lambda: mw._align_selected("right"))
    tb_layout.addAction(act_align_right)

    tb_layout.addSeparator()

    act_align_top = QtGui.QAction("⟰", mw)
    act_align_top.setToolTip("Align selected items to top edge")
    act_align_top.triggered.connect(lambda: mw._align_selected("top"))
    tb_layout.addAction(act_align_top)

    act_align_vcenter = QtGui.QAction("↕", mw)
    act_align_vcenter.setToolTip("Align selected items to vertical center")
    act_align_vcenter.triggered.connect(lambda: mw._align_selected("vcenter"))
    tb_layout.addAction(act_align_vcenter)

    act_align_bottom = QtGui.QAction("⟱", mw)
    act_align_bottom.setToolTip("Align selected items to bottom edge")
    act_align_bottom.triggered.connect(lambda: mw._align_selected("bottom"))
    tb_layout.addAction(act_align_bottom)

    # ---- Distribute ----
    tb_layout.addSeparator()
    tb_layout.addWidget(QtWidgets.QLabel("Distrib:"))

    act_dist_h = QtGui.QAction("H", mw)
    act_dist_h.setToolTip("Distribute selected items evenly across horizontal space")
    act_dist_h.triggered.connect(lambda: mw._distribute_selected("h"))
    tb_layout.addAction(act_dist_h)

    act_dist_v = QtGui.QAction("V", mw)
    act_dist_v.setToolTip("Distribute selected items evenly across vertical space")
    act_dist_v.triggered.connect(lambda: mw._distribute_selected("v"))
    tb_layout.addAction(act_dist_v)

    # ---- Group / Ungroup ----
    tb_layout.addSeparator()
    tb_layout.addWidget(QtWidgets.QLabel("Group:"))

    act_group = QtGui.QAction("Grp", mw)
    act_group.setToolTip("Group selected items together (Ctrl+G)\nGrouped items move as one unit")
    act_group.setShortcut("Ctrl+G")
    act_group.triggered.connect(mw._group_selected)
    tb_layout.addAction(act_group)

    act_ungroup = QtGui.QAction("Ungrp", mw)
    act_ungroup.setToolTip("Ungroup selected group (Ctrl+Shift+G)\nSeparates items in a group")
    act_ungroup.setShortcut("Ctrl+Shift+G")
    act_ungroup.triggered.connect(mw._ungroup_selected)
    tb_layout.addAction(act_ungroup)

    # ---- Z-order ----
    tb_layout.addSeparator()
    tb_layout.addWidget(QtWidgets.QLabel("Order:"))

    act_front = QtGui.QAction("Front", mw)
    act_front.setToolTip("Bring to front\nMove selected item above all others")
    act_front.triggered.connect(lambda: mw._change_z_order("front"))
    tb_layout.addAction(act_front)

    act_back = QtGui.QAction("Back", mw)
    act_back.setToolTip("Send to back\nMove selected item below all others")
    act_back.triggered.connect(lambda: mw._change_z_order("back"))
    tb_layout.addAction(act_back)

    act_up = QtGui.QAction("Raise", mw)
    act_up.setToolTip("Bring forward\nMove selected item one layer up")
    act_up.triggered.connect(lambda: mw._change_z_order("up"))
    tb_layout.addAction(act_up)

    act_down = QtGui.QAction("Lower", mw)
    act_down.setToolTip("Send backward\nMove selected item one layer down")
    act_down.triggered.connect(lambda: mw._change_z_order("down"))
    tb_layout.addAction(act_down)

    # ---- Lock / Hide ----
    tb_layout.addSeparator()
    tb_layout.addWidget(QtWidgets.QLabel("Lock:"))

    act_lock = QtGui.QAction("Lock", mw)
    act_lock.setToolTip("Lock selected items\nPrevents moving, resizing, and editing")
    act_lock.triggered.connect(mw._lock_selected)
    tb_layout.addAction(act_lock)

    act_unlock = QtGui.QAction("Unlock", mw)
    act_unlock.setToolTip("Unlock selected items\nAllows moving, resizing, and editing")
    act_unlock.triggered.connect(mw._unlock_selected)
    tb_layout.addAction(act_unlock)

    act_hide = QtGui.QAction("Hide", mw)
    act_hide.setToolTip("Hide selected items\nMakes items invisible (won't print)")
    act_hide.triggered.connect(mw._hide_selected)
    tb_layout.addAction(act_hide)

    act_show_all = QtGui.QAction("Unhide", mw)
    act_show_all.setToolTip("Show all hidden items\nMakes all items visible again")
    act_show_all.triggered.connect(mw._show_all_hidden)
    tb_layout.addAction(act_show_all)

    # ---- Baseline ----
    tb_layout.addSeparator()
    tb_layout.addWidget(QtWidgets.QLabel("Baseline:"))

    mw.sb_baseline_mm = QtWidgets.QDoubleSpinBox()
    mw.sb_baseline_mm.setRange(0.5, 20.0)
    mw.sb_baseline_mm.setDecimals(2)
    mw.sb_baseline_mm.setSingleStep(0.5)
    mw.sb_baseline_mm.setValue(4.0)
    mw.sb_baseline_mm.setSuffix(" mm")
    mw.sb_baseline_mm.setToolTip(
        "Baseline grid spacing in millimeters\n"
        "Used to align text to consistent vertical rhythm"
    )
    tb_layout.addWidget(mw.sb_baseline_mm)

    act_baseline_apply = QtGui.QAction("Apply", mw)
    act_baseline_apply.setToolTip(
        "Snap to baseline grid\n"
        "Aligns selected items' Y position to baseline grid"
    )
    act_baseline_apply.triggered.connect(mw._apply_baseline_to_selected)
    tb_layout.addAction(act_baseline_apply)

    # Shortcut: Delete selected items
    mw._shortcut_delete = QtGui.QShortcut(QtGui.QKeySequence.Delete, mw)
    mw._shortcut_delete.activated.connect(mw._delete_selected_items)

    # Duplicate shortcut
    mw._shortcut_duplicate = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+D"), mw)
    mw._shortcut_duplicate.activated.connect(mw._duplicate_selected_items)

    # =============================
    # Menubar
    # =============================
    menubar = mw.menuBar()

    # File
    file_menu = menubar.addMenu("&File")

    act_open = QtGui.QAction("Open Template…", mw)
    act_open.setShortcut("Ctrl+O")
    act_open.setToolTip("Open template from file (Ctrl+O)")
    act_open.triggered.connect(mw.load_template)
    file_menu.addAction(act_open)

    act_save_menu = QtGui.QAction("Save Template…", mw)
    act_save_menu.setShortcut("Ctrl+S")
    act_save_menu.setToolTip("Save current template to file (Ctrl+S)")
    act_save_menu.triggered.connect(mw.save_template)
    file_menu.addAction(act_save_menu)

    file_menu.addSeparator()
    mw.recent_menu = file_menu.addMenu("Recent Files")
    mw._refresh_recent_menu()
    file_menu.addSeparator()

    file_menu.addSeparator()

    act_export_png = QtGui.QAction("Export as PNG…", mw)
    act_export_png.setToolTip("Export template as PNG image file")
    act_export_png.triggered.connect(mw.export_png)
    file_menu.addAction(act_export_png)

    act_export_pdf = QtGui.QAction("Export as PDF…", mw)
    act_export_pdf.setToolTip("Export template as PDF document")
    act_export_pdf.triggered.connect(mw.export_pdf)
    file_menu.addAction(act_export_pdf)

    file_menu.addSeparator()

    act_file_preview = QtGui.QAction("Print Preview…", mw)
    act_file_preview.setShortcut("Ctrl+Shift+P")
    act_file_preview.setToolTip("Preview how the receipt will look before printing (Ctrl+Shift+P)")
    act_file_preview.triggered.connect(mw.preview_print)
    file_menu.addAction(act_file_preview)

    act_file_print = QtGui.QAction("Print…", mw)
    act_file_print.setShortcut("Ctrl+P")
    act_file_print.setToolTip("Send template to thermal printer (Ctrl+P)")
    act_file_print.triggered.connect(mw.print_now)
    file_menu.addAction(act_file_print)

    file_menu.addSeparator()

    act_exit = QtGui.QAction("Exit", mw)
    act_exit.setToolTip("Exit the application")
    act_exit.triggered.connect(mw.close)
    file_menu.addAction(act_exit)

    # Edit menu
    edit_menu = menubar.addMenu("&Edit")

    edit_menu.addAction(act_undo)
    edit_menu.addAction(act_redo)
    edit_menu.addSeparator()

    act_duplicate = QtGui.QAction("Duplicate", mw)
    act_duplicate.setToolTip("Duplicate selected items (Ctrl+D)")
    act_duplicate.triggered.connect(mw._duplicate_selected_items)
    edit_menu.addAction(act_duplicate)

    act_set_dup_offset = QtGui.QAction("Set Duplicate Offset…", mw)
    act_set_dup_offset.setToolTip("Change the offset used when duplicating items")
    act_set_dup_offset.triggered.connect(mw._set_duplicate_offset_dialog)
    edit_menu.addAction(act_set_dup_offset)

    # View
    mw.action_margins = QtGui.QAction("Show Printable Margins", mw)
    mw.action_margins.setCheckable(True)
    mw.action_margins.setChecked(True)
    mw.action_margins.setShortcut("Ctrl+M")
    mw.action_margins.setToolTip(
        "Toggle margin guides\n"
        "Shows printable area boundaries (Ctrl+M)"
    )
    mw.action_margins.toggled.connect(mw._on_toggle_margins)

    view_menu = menubar.addMenu("&View")
    view_menu.addAction(mw.action_margins)

    # Dark mode toggle
    mw.action_dark_mode = QtGui.QAction("Dark Mode", mw)
    mw.action_dark_mode.setCheckable(True)
    mw.action_dark_mode.setChecked(mw.settings.value("ui/dark_mode", False, type=bool))
    mw.action_dark_mode.setToolTip("Toggle dark mode appearance")
    mw.action_dark_mode.toggled.connect(mw._toggle_dark_mode)
    view_menu.addAction(mw.action_dark_mode)

    view_menu.addSeparator()

    # Insert
    insert_menu = menubar.addMenu("&Insert")

    act_add_text = QtGui.QAction("Text", mw)
    act_add_text.setShortcut("Ctrl+Shift+T")
    act_add_text.setToolTip("Insert text element (Ctrl+Shift+T)\nAdd editable text to receipt")
    act_add_text.triggered.connect(mw.add_text)
    insert_menu.addAction(act_add_text)

    act_add_barcode = QtGui.QAction("Barcode", mw)
    act_add_barcode.setShortcut("Ctrl+Shift+B")
    act_add_barcode.setToolTip("Insert barcode element (Ctrl+Shift+B)\nAdd scannable barcode")
    act_add_barcode.triggered.connect(mw.add_barcode)
    insert_menu.addAction(act_add_barcode)

    insert_menu.addSeparator()

    act_add_image = QtGui.QAction("Image…", mw)
    act_add_image.setShortcut("Ctrl+Shift+I")
    act_add_image.setToolTip("Insert image from file (Ctrl+Shift+I)\nAdd logo or picture")
    act_add_image.triggered.connect(mw.add_image)
    insert_menu.addAction(act_add_image)

    insert_menu.addSeparator()

    act_add_line = QtGui.QAction("Line", mw)
    act_add_line.setShortcut("Ctrl+Shift+L")
    act_add_line.setToolTip("Insert line (Ctrl+Shift+L)\nAdd horizontal or vertical line")
    act_add_line.triggered.connect(mw.add_line)
    insert_menu.addAction(act_add_line)

    if hasattr(mw, "add_rect"):
        act_add_rect = QtGui.QAction("Rectangle", mw)
        act_add_rect.setShortcut("Ctrl+Shift+R")
        act_add_rect.setToolTip("Insert rectangle (Ctrl+Shift+R)\nAdd rectangular shape")
        act_add_rect.triggered.connect(mw.add_rect)
        insert_menu.addAction(act_add_rect)

    if hasattr(mw, "add_circle"):
        act_add_circle = QtGui.QAction("Circle", mw)
        act_add_circle.setShortcut("Ctrl+Shift+C")
        act_add_circle.setToolTip("Insert circle (Ctrl+Shift+C)\nAdd circular shape")
        act_add_circle.triggered.connect(mw.add_circle)
        insert_menu.addAction(act_add_circle)

    if hasattr(mw, "add_star"):
        act_add_star = QtGui.QAction("Star", mw)
        act_add_star.setShortcut("Ctrl+Shift+S")
        act_add_star.setToolTip("Insert star (Ctrl+Shift+S)\nAdd star shape")
        act_add_star.triggered.connect(mw.add_star)
        insert_menu.addAction(act_add_star)

    if hasattr(mw, "add_arrow"):
        act_add_arrow = QtGui.QAction("Arrow", mw)
        act_add_arrow.setShortcut("Ctrl+Shift+A")
        act_add_arrow.setToolTip("Insert arrow (Ctrl+Shift+A)\nAdd directional arrow")
        act_add_arrow.triggered.connect(mw.add_arrow)
        insert_menu.addAction(act_add_arrow)

    if hasattr(mw, "add_diamond"):
        act_add_diamond = QtGui.QAction("Diamond", mw)
        act_add_diamond.setShortcut("Ctrl+Shift+D")
        act_add_diamond.setToolTip("Insert diamond (Ctrl+Shift+D)\nAdd diamond shape")
        act_add_diamond.triggered.connect(mw.add_diamond)
        insert_menu.addAction(act_add_diamond)

    # Layout menu (column guides, baseline, presets)
    layout_menu = menubar.addMenu("&Layout")

    act_cols = QtGui.QAction("Set Column Guides…", mw)
    act_cols.setToolTip("Create vertical column guides for alignment")
    act_cols.triggered.connect(mw._set_column_guides_dialog)
    layout_menu.addAction(act_cols)

    act_cols_clear = QtGui.QAction("Clear Column Guides", mw)
    act_cols_clear.setToolTip("Remove all column guides")
    act_cols_clear.triggered.connect(mw._clear_column_guides)
    layout_menu.addAction(act_cols_clear)

    layout_menu.addSeparator()

    act_baseline_menu = QtGui.QAction("Apply Baseline to Selection", mw)
    act_baseline_menu.setToolTip("Snap selected items to baseline grid")
    act_baseline_menu.triggered.connect(mw._apply_baseline_to_selected)
    layout_menu.addAction(act_baseline_menu)

    presets_menu = layout_menu.addMenu("Presets")

    act_preset_simple = QtGui.QAction("Simple Store Receipt", mw)
    act_preset_simple.setToolTip("Load basic retail receipt template")
    act_preset_simple.triggered.connect(
        lambda: mw._apply_preset("simple_store_receipt")
    )
    presets_menu.addAction(act_preset_simple)

    act_preset_kitchen = QtGui.QAction("Kitchen Ticket", mw)
    act_preset_kitchen.setToolTip("Load restaurant kitchen order template")
    act_preset_kitchen.triggered.connect(
        lambda: mw._apply_preset("kitchen_ticket")
    )
    presets_menu.addAction(act_preset_kitchen)

    act_preset_detailed = QtGui.QAction("Detailed Store Receipt", mw)
    act_preset_detailed.setToolTip("Load detailed retail receipt with itemization")
    act_preset_detailed.triggered.connect(
        lambda: mw._apply_preset("detailed_store_receipt")
    )
    presets_menu.addAction(act_preset_detailed)

    act_preset_pickup = QtGui.QAction("Pickup Ticket", mw)
    act_preset_pickup.setToolTip("Load order pickup ticket template")
    act_preset_pickup.triggered.connect(
        lambda: mw._apply_preset("pickup_ticket")
    )
    presets_menu.addAction(act_preset_pickup)

    act_preset_todo = QtGui.QAction("To-Do / Checklist", mw)
    act_preset_todo.setToolTip("Load checklist template")
    act_preset_todo.triggered.connect(
        lambda: mw._apply_preset("todo_checklist")
    )
    presets_menu.addAction(act_preset_todo)

    act_preset_message = QtGui.QAction("Message Note", mw)
    act_preset_message.setToolTip("Load message note template")
    act_preset_message.triggered.connect(
        lambda: mw._apply_preset("message_note")
    )
    presets_menu.addAction(act_preset_message)

    act_preset_fortune = QtGui.QAction("Fortune Cookie", mw)
    act_preset_fortune.setToolTip("Load fortune cookie slip template")
    act_preset_fortune.triggered.connect(
        lambda: mw._apply_preset("fortune_cookie")
    )
    presets_menu.addAction(act_preset_fortune)

    # =============================
    # Help menu
    # =============================
    help_menu = menubar.addMenu("&Help")

    act_shortcuts = QtGui.QAction("Keyboard Shortcuts…", mw)
    act_shortcuts.setToolTip("View all keyboard shortcuts")
    act_shortcuts.triggered.connect(mw._show_keyboard_shortcuts_dialog)
    help_menu.addAction(act_shortcuts)
