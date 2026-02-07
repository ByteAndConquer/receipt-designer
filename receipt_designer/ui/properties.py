from __future__ import annotations

from typing import Optional, List

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.models import Element
from .items import (
    GItem,
    GLineItem,
    GRectItem,
    GEllipseItem,
    GStarItem,
    GArrowItem,
    GDiamondItem,
)
from .views import PX_PER_MM  # for px <-> mm conversions
from ..core.barcodes import validate_barcode_data, BarcodeValidationError
from ..core.commands import MoveResizeCmd, PropertyChangeCmd

class PropertiesPanel(QtWidgets.QWidget):
    """
    Right-side properties panel.

    Modes:
      - "text":        GItem with elem.kind == "text"
      - "barcode":     GItem with elem.kind == "barcode"
      - "line":        plain GLineItem
      - "arrow":       GArrowItem
      - "rect":        GRectItem
      - "circle":      GEllipseItem
      - "star":        GStarItem
    """

    element_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_window = parent  # Reference to main window for inline editor check
        self._current_item: Optional[QtWidgets.QGraphicsItem] = None
        self._current_elem: Optional[Element] = None
        self._updating_ui = False
        self._mode: Optional[str] = None
        self._undo_stack: Optional[QtGui.QUndoStack] = None

        self._groups: list[QtWidgets.QGroupBox] = []

        # ========== NEW: Patch 8 - Text edit undo buffering ==========
        # Text content buffering
        self._text_undo_timer = QtCore.QTimer(self)
        self._text_undo_timer.setSingleShot(True)
        self._text_undo_timer.setInterval(1000)  # 1 second pause = commit to undo
        self._text_undo_timer.timeout.connect(self._commit_text_to_undo)
        
        self._pending_text_item = None
        self._pending_text_old_value = None
        
        # Font size buffering (optional but recommended)
        self._font_size_undo_timer = QtCore.QTimer(self)
        self._font_size_undo_timer.setSingleShot(True)
        self._font_size_undo_timer.setInterval(500)  # 500ms for numeric inputs
        self._font_size_undo_timer.timeout.connect(self._commit_font_size_to_undo)
        
        self._pending_font_size_item = None
        self._pending_font_size_old_value = None
        # ========== END NEW ==========

        self._build_ui()
        self._set_active(False)
        self.lbl_target.setText("")
        

    def bind_item(self, item: Optional[GItem]) -> None:
        """
        Backwards-compat wrapper for older MainWindow code.

        New flow is set_target_from_selection([...]).
        """
        if item is None:
            self.set_target_from_selection([])
        else:
            self.set_target_from_selection([item])



    # --------------------- external config ---------------------

    def set_undo_stack(self, undo_stack: QtGui.QUndoStack) -> None:
        """Inject the shared QUndoStack from MainWindow."""
        self._undo_stack = undo_stack

    # --------------------- sizing hints ---------------------
    def sizeHint(self) -> QtCore.QSize:  # type: ignore[override]
        """
        Prefer a reasonable width so the dock doesn't try to be huge
        and cause horizontal scrolling.
        """
        base = super().sizeHint()
        return QtCore.QSize(280, base.height())

    def minimumSizeHint(self) -> QtCore.QSize:  # type: ignore[override]
        """
        Allow the dock to shrink to something narrower without
        insisting on a giant width (which triggers horizontal scroll).
        """
        return QtCore.QSize(220, 0)


    # --------------------- helpers: mm/px ---------------------

    def _mm_to_px(self, mm: float) -> float:
        try:
            factor = float(PX_PER_MM) if PX_PER_MM else 1.0
        except Exception:
            factor = 1.0
        return mm * factor

    def _px_to_mm(self, px: float) -> float:
        try:
            factor = float(PX_PER_MM) if PX_PER_MM else 1.0
        except Exception:
            factor = 1.0
        if factor <= 0:
            return px
        return px / factor

    def _is_inline_editing_item(self, item) -> bool:
        """Check if the given item is being edited inline on the canvas."""
        main_window = self._main_window
        if main_window is None:
            return False
        inline_editor = getattr(main_window, "_inline_editor", None)
        if inline_editor is None:
            return False
        if not inline_editor.isEditing():
            return False
        return inline_editor.currentItem() is item

    # --------------------- generic property helper ---------------------

    def _push_elem_property(self, prop: str, new_value, label: str = "Change property"):
        """
        Either push a PropertyChangeCmd onto the undo stack, or apply directly
        if no undo stack is configured.
        """
        if self._current_elem is None:
            return

        # No undo stack → just set + repaint
        if self._undo_stack is None:
            setattr(self._current_elem, prop, new_value)
            self._touch_item()
            return

        old_value = getattr(self._current_elem, prop, None)
        if old_value == new_value:
            return

        cmd = PropertyChangeCmd(
            self._current_elem,
            prop,
            old_value,
            new_value,
            text=label,
            item=self._current_item,
        )
        self._undo_stack.push(cmd)
        # QUndoStack will immediately call redo() on the cmd.
        self.element_changed.emit()

    # --------------------- UI construction ---------------------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # --- Target summary ---
        self.lbl_target = QtWidgets.QLabel("")
        font_bold = self.lbl_target.font()
        font_bold.setBold(True)
        self.lbl_target.setFont(font_bold)
        layout.addWidget(self.lbl_target)

        layout.addSpacing(4)
        layout.addWidget(self._line_separator())

        # --- Text content ---
        self.grp_text = QtWidgets.QGroupBox("Text")
        txt_layout = QtWidgets.QVBoxLayout(self.grp_text)

        self.txt_content = QtWidgets.QPlainTextEdit()
        self.txt_content.setPlaceholderText(
            "Text content (supports {{date}}, {{time}}, {{var:name}})"
        )
        self.txt_content.textChanged.connect(self._on_text_changed)
        txt_layout.addWidget(self.txt_content)

        layout.addWidget(self.grp_text)

        # --- Font ---
        self.grp_font = QtWidgets.QGroupBox("Font")
        font_layout = QtWidgets.QFormLayout(self.grp_font)

        self.font_combo = QtWidgets.QFontComboBox()
        self.font_combo.currentFontChanged.connect(self._on_font_changed)
        font_layout.addRow("Family:", self.font_combo)

        self.spin_font_size = QtWidgets.QSpinBox()
        self.spin_font_size.setRange(1, 300)
        self.spin_font_size.valueChanged.connect(self._on_font_size_changed)
        font_layout.addRow("Size (pt):", self.spin_font_size)

        font_style_row = QtWidgets.QHBoxLayout()
        self.chk_bold = QtWidgets.QCheckBox("Bold")
        self.chk_bold.toggled.connect(self._on_bold_toggled)
        self.chk_italic = QtWidgets.QCheckBox("Italic")
        self.chk_italic.toggled.connect(self._on_italic_toggled)
        font_style_row.addWidget(self.chk_bold)
        font_style_row.addWidget(self.chk_italic)
        font_style_row.addStretch(1)
        font_layout.addRow("", font_style_row)

        layout.addWidget(self.grp_font)

        # --- Alignment ---
        self.grp_align = QtWidgets.QGroupBox("Alignment")
        align_layout = QtWidgets.QFormLayout(self.grp_align)

        self.combo_h_align = QtWidgets.QComboBox()
        self.combo_h_align.addItems(["Left", "Center", "Right"])
        self.combo_h_align.currentTextChanged.connect(self._on_h_align_changed)
        align_layout.addRow("Horizontal:", self.combo_h_align)

        self.combo_v_align = QtWidgets.QComboBox()
        self.combo_v_align.addItems(["Top", "Middle", "Bottom"])
        self.combo_v_align.currentTextChanged.connect(self._on_v_align_changed)
        align_layout.addRow("Vertical:", self.combo_v_align)

        layout.addWidget(self.grp_align)

        # --- Wrapping & lines ---
        self.grp_wrap = QtWidgets.QGroupBox("Wrapping")
        wrap_layout = QtWidgets.QFormLayout(self.grp_wrap)

        self.combo_wrap = QtWidgets.QComboBox()
        self.combo_wrap.addItems(["Word wrap", "Anywhere"])
        self.combo_wrap.currentTextChanged.connect(self._on_wrap_mode_changed)
        wrap_layout.addRow("Mode:", self.combo_wrap)

        self.chk_shrink = QtWidgets.QCheckBox("Shrink to fit")
        self.chk_shrink.toggled.connect(self._on_shrink_toggled)
        wrap_layout.addRow("", self.chk_shrink)

        self.spin_max_lines = QtWidgets.QSpinBox()
        self.spin_max_lines.setRange(0, 50)
        self.spin_max_lines.setSpecialValueText("0 (unlimited)")
        self.spin_max_lines.valueChanged.connect(self._on_max_lines_changed)
        wrap_layout.addRow("Max lines:", self.spin_max_lines)

        layout.addWidget(self.grp_wrap)

        # --- Text Padding ---
        self.grp_padding = QtWidgets.QGroupBox("Text Padding")
        padding_layout = QtWidgets.QFormLayout(self.grp_padding)

        self.spin_pad_left = QtWidgets.QDoubleSpinBox()
        self.spin_pad_left.setRange(0.0, 50.0)
        self.spin_pad_left.setSingleStep(0.5)
        self.spin_pad_left.setSuffix(" px")
        self.spin_pad_left.valueChanged.connect(self._on_pad_left_changed)
        padding_layout.addRow("Left:", self.spin_pad_left)

        self.spin_pad_right = QtWidgets.QDoubleSpinBox()
        self.spin_pad_right.setRange(0.0, 50.0)
        self.spin_pad_right.setSingleStep(0.5)
        self.spin_pad_right.setSuffix(" px")
        self.spin_pad_right.valueChanged.connect(self._on_pad_right_changed)
        padding_layout.addRow("Right:", self.spin_pad_right)

        self.spin_pad_top = QtWidgets.QDoubleSpinBox()
        self.spin_pad_top.setRange(0.0, 50.0)
        self.spin_pad_top.setSingleStep(0.5)
        self.spin_pad_top.setSuffix(" px")
        self.spin_pad_top.valueChanged.connect(self._on_pad_top_changed)
        padding_layout.addRow("Top:", self.spin_pad_top)

        self.spin_pad_bottom = QtWidgets.QDoubleSpinBox()
        self.spin_pad_bottom.setRange(0.0, 50.0)
        self.spin_pad_bottom.setSingleStep(0.5)
        self.spin_pad_bottom.setSuffix(" px")
        self.spin_pad_bottom.valueChanged.connect(self._on_pad_bottom_changed)
        padding_layout.addRow("Bottom:", self.spin_pad_bottom)

        layout.addWidget(self.grp_padding)

        # --- Barcode ---
        self.grp_barcode = QtWidgets.QGroupBox("Barcode")
        bc_layout = QtWidgets.QFormLayout(self.grp_barcode)

        self.combo_bc_type = QtWidgets.QComboBox()
        self.combo_bc_type.addItems(
            [
                "Code128",
                "Code39",
                "EAN-13",
                "UPC-A",
                "UPC-E",
                "ITF",
                "ITF-14",
                "Codabar",
                "GS1-128",
                "QR Code",
                "Data Matrix",
                "PDF417",
                "Aztec",
                "GS1 DataMatrix",
            ]
        )
        self.combo_bc_type.currentTextChanged.connect(self._on_barcode_type_changed)
        bc_layout.addRow("Type:", self.combo_bc_type)

        self.edit_bc_data = QtWidgets.QLineEdit()
        self.edit_bc_data.setPlaceholderText("Data / payload")
        self.edit_bc_data.textEdited.connect(self._on_barcode_data_changed)
        bc_layout.addRow("Data:", self.edit_bc_data)

        # Barcode validation error label
        self.lbl_bc_error = QtWidgets.QLabel("")
        self.lbl_bc_error.setStyleSheet("color: red; font-size: 10px;")
        self.lbl_bc_error.setWordWrap(True)
        self.lbl_bc_error.hide()
        bc_layout.addRow(self.lbl_bc_error)

        # Human-readable text controls
        self.combo_bc_hr_pos = QtWidgets.QComboBox()
        self.combo_bc_hr_pos.addItems(["Below", "Above", "None"])
        self.combo_bc_hr_pos.currentTextChanged.connect(self._on_barcode_hr_pos_changed)
        bc_layout.addRow("Human-readable:", self.combo_bc_hr_pos)

        self.font_bc = QtWidgets.QFontComboBox()
        self.font_bc.currentFontChanged.connect(self._on_barcode_hr_font_changed)
        bc_layout.addRow("HRT font:", self.font_bc)

        self.spin_bc_font_size = QtWidgets.QSpinBox()
        self.spin_bc_font_size.setRange(4, 48)
        self.spin_bc_font_size.setValue(10)
        self.spin_bc_font_size.valueChanged.connect(
            self._on_barcode_hr_font_size_changed
        )
        bc_layout.addRow("HRT size (pt):", self.spin_bc_font_size)

        layout.addWidget(self.grp_barcode)

        # --- Layout (geometry: x/y/w/h in mm) ---
        self.grp_layout = QtWidgets.QGroupBox("Layout")
        layout_form = QtWidgets.QFormLayout(self.grp_layout)

        self.sp_x = QtWidgets.QDoubleSpinBox()
        self.sp_x.setRange(-1000.0, 1000.0)
        self.sp_x.setDecimals(2)
        self.sp_x.setSuffix(" mm")
        self.sp_x.valueChanged.connect(self._on_geom_changed)

        self.sp_y = QtWidgets.QDoubleSpinBox()
        self.sp_y.setRange(-1000.0, 1000.0)
        self.sp_y.setDecimals(2)
        self.sp_y.setSuffix(" mm")
        self.sp_y.valueChanged.connect(self._on_geom_changed)

        self.sp_w = QtWidgets.QDoubleSpinBox()
        self.sp_w.setRange(0.1, 2000.0)
        self.sp_w.setDecimals(2)
        self.sp_w.setSuffix(" mm")
        self.sp_w.valueChanged.connect(self._on_geom_changed)

        self.sp_h = QtWidgets.QDoubleSpinBox()
        self.sp_h.setRange(0.1, 2000.0)
        self.sp_h.setDecimals(2)
        self.sp_h.setSuffix(" mm")
        self.sp_h.valueChanged.connect(self._on_geom_changed)

        layout_form.addRow("X:", self.sp_x)
        layout_form.addRow("Y:", self.sp_y)
        layout_form.addRow("Width:", self.sp_w)
        layout_form.addRow("Height:", self.sp_h)

        layout.addWidget(self.grp_layout)

        # --- Shape / Stroke (for lines + shapes) ---
        self.grp_shape = QtWidgets.QGroupBox("Shape / Stroke")
        shape_layout = QtWidgets.QFormLayout(self.grp_shape)

        # Line width
        self.spin_line_width = QtWidgets.QDoubleSpinBox()
        self.spin_line_width.setRange(0.1, 10.0)
        self.spin_line_width.setSingleStep(0.1)
        self.spin_line_width.setValue(1.0)
        self.spin_line_width.valueChanged.connect(self._on_line_width_changed)
        shape_layout.addRow("Line width:", self.spin_line_width)

        # Line style
        self.combo_line_style = QtWidgets.QComboBox()
        self.combo_line_style.addItems(
            ["Solid", "Dashed", "Dotted", "Dash-dot", "Perforation"]
        )
        self.combo_line_style.currentTextChanged.connect(self._on_line_style_changed)
        shape_layout.addRow("Line style:", self.combo_line_style)

        # Star points
        self.spin_star_points = QtWidgets.QSpinBox()
        self.spin_star_points.setRange(3, 24)
        self.spin_star_points.setValue(5)
        self.spin_star_points.valueChanged.connect(self._on_star_points_changed)
        shape_layout.addRow("Star points:", self.spin_star_points)

        # Circle diameter
        self.spin_circle_diam = QtWidgets.QDoubleSpinBox()
        self.spin_circle_diam.setRange(1.0, 500.0)
        self.spin_circle_diam.setSingleStep(1.0)
        self.spin_circle_diam.valueChanged.connect(self._on_circle_diameter_changed)
        shape_layout.addRow("Circle diameter (mm):", self.spin_circle_diam)

        # Rect: rounded corners / pill mode
        self.spin_corner_radius = QtWidgets.QDoubleSpinBox()
        self.spin_corner_radius.setRange(0.0, 200.0)
        self.spin_corner_radius.setSingleStep(0.5)
        self.spin_corner_radius.valueChanged.connect(self._on_corner_radius_changed)
        shape_layout.addRow("Corner radius (mm):", self.spin_corner_radius)

        self.chk_pill = QtWidgets.QCheckBox("Pill mode (full rounding)")
        self.chk_pill.toggled.connect(self._on_pill_toggled)
        shape_layout.addRow("", self.chk_pill)

        # Arrow-specific
        self.combo_arrow_side = QtWidgets.QComboBox()
        self.combo_arrow_side.addItems(["End (→)", "Start (←)"])
        self.combo_arrow_side.currentTextChanged.connect(
            self._on_arrow_side_changed
        )
        shape_layout.addRow("Arrow head at:", self.combo_arrow_side)

        self.spin_arrow_len = QtWidgets.QDoubleSpinBox()
        self.spin_arrow_len.setRange(0.5, 100.0)
        self.spin_arrow_len.setSingleStep(0.5)
        self.spin_arrow_len.valueChanged.connect(self._on_arrow_len_changed)
        shape_layout.addRow("Head length (mm):", self.spin_arrow_len)

        self.spin_arrow_width = QtWidgets.QDoubleSpinBox()
        self.spin_arrow_width.setRange(0.5, 100.0)
        self.spin_arrow_width.setSingleStep(0.5)
        self.spin_arrow_width.valueChanged.connect(self._on_arrow_width_changed)
        shape_layout.addRow("Head width (mm):", self.spin_arrow_width)

        layout.addWidget(self.grp_shape)

        layout.addStretch(1)

        self._groups = [
            self.grp_text,
            self.grp_font,
            self.grp_align,
            self.grp_wrap,
            self.grp_padding,
            self.grp_layout,
            self.grp_barcode,
            self.grp_shape,
        ]

        # Let the panel shrink nicely inside the dock
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred,
            QtWidgets.QSizePolicy.Expanding,
        )


    def _line_separator(self) -> QtWidgets.QFrame:
        f = QtWidgets.QFrame()
        f.setFrameShape(QtWidgets.QFrame.HLine)
        f.setFrameShadow(QtWidgets.QFrame.Sunken)
        return f

    def _set_active(self, active: bool):
        for g in self._groups:
            g.setVisible(active)

    def _set_layout_enabled(self, ex: bool, ey: bool, ew: bool, eh: bool):
        self.sp_x.setEnabled(ex)
        self.sp_y.setEnabled(ey)
        self.sp_w.setEnabled(ew)
        self.sp_h.setEnabled(eh)

    # --------------------- selection binding ---------------------

    def set_target_from_selection(self, items: List[QtWidgets.QGraphicsItem]):
        """
        Called by MainWindow when selection changes.
        """

        # ========== Patch 8: Commit pending edits before switching items ==========
        if self._text_undo_timer.isActive():
            self._text_undo_timer.stop()
            self._commit_text_to_undo()
        
        if self._font_size_undo_timer.isActive():
            self._font_size_undo_timer.stop()
            self._commit_font_size_to_undo()
        # ========== END Patch 8 ==========

        self._updating_ui = True
        try:
            self._current_item = None
            self._current_elem = None
            self._mode = None

            if len(items) != 1:
                self.lbl_target.setText("")
                self._set_active(False)
                self.lbl_bc_error.hide()
                return

            item = items[0]

            # --- helper: populate stroke style from QPen ---
            def _fill_stroke_from_pen(pen: QtGui.QPen):
                self.spin_line_width.setValue(float(pen.widthF()))
                style = pen.style()
                if style == QtCore.Qt.SolidLine:
                    self.combo_line_style.setCurrentText("Solid")
                elif style == QtCore.Qt.DashLine:
                    self.combo_line_style.setCurrentText("Dashed")
                elif style == QtCore.Qt.DotLine:
                    self.combo_line_style.setCurrentText("Dotted")
                elif style == QtCore.Qt.DashDotLine:
                    self.combo_line_style.setCurrentText("Dash-dot")
                elif style == QtCore.Qt.CustomDashLine:
                    self.combo_line_style.setCurrentText("Perforation")
                else:
                    self.combo_line_style.setCurrentText("Solid")

            # --- TEXT / BARCODE: GItem with elem.kind ---
            if isinstance(item, GItem):
                elem = item.elem
                kind = getattr(elem, "kind", "text")

                # --- TEXT MODE ---
                if kind == "text":
                    self._mode = "text"
                    self._current_item = item
                    self._current_elem = elem

                    self.lbl_target.setText("Text element")
                    self._set_active(True)

                    # show text, hide barcode/shape
                    self.grp_text.setVisible(True)
                    self.grp_font.setVisible(True)
                    self.grp_align.setVisible(True)
                    self.grp_wrap.setVisible(True)
                    self.grp_padding.setVisible(True)
                    self.grp_layout.setVisible(True)
                    self.grp_barcode.setVisible(False)
                    self.grp_shape.setVisible(False)

                    self._set_layout_enabled(True, True, True, True)

                    # Geometry (px → mm)
                    x_px = float(getattr(elem, "x", 0.0))
                    y_px = float(getattr(elem, "y", 0.0))
                    w_px = float(getattr(elem, "w", 160.0))
                    h_px = float(getattr(elem, "h", 40.0))

                    self.sp_x.setValue(self._px_to_mm(x_px))
                    self.sp_y.setValue(self._px_to_mm(y_px))
                    self.sp_w.setValue(self._px_to_mm(w_px))
                    self.sp_h.setValue(self._px_to_mm(h_px))

                    # Text properties
                    text = getattr(elem, "text", "") or ""
                    font_family = getattr(elem, "font_family", "Arial")

                    font_pt = getattr(elem, "font_point", None)
                    if font_pt is None:
                        font_pt = getattr(elem, "font_size", 12)
                    try:
                        font_pt = int(font_pt or 12)
                    except Exception:
                        font_pt = 12

                    bold = bool(getattr(elem, "bold", False))
                    italic = bool(getattr(elem, "italic", False))
                    h_align = getattr(elem, "h_align", "left")
                    v_align = getattr(elem, "v_align", "top")
                    wrap_mode = getattr(elem, "wrap_mode", "word")
                    shrink = bool(getattr(elem, "shrink_to_fit", False))
                    max_lines = int(getattr(elem, "max_lines", 0) or 0)

                    # Padding (already implemented in items.py)
                    pad_left = float(getattr(elem, "pad_left", 0.0) or 0.0)
                    pad_right = float(getattr(elem, "pad_right", 0.0) or 0.0)
                    pad_top = float(getattr(elem, "pad_top", 0.0) or 0.0)
                    pad_bottom = float(getattr(elem, "pad_bottom", 0.0) or 0.0)

                    self.spin_pad_left.setValue(pad_left)
                    self.spin_pad_right.setValue(pad_right)
                    self.spin_pad_top.setValue(pad_top)
                    self.spin_pad_bottom.setValue(pad_bottom)

                    # 👉 Only update the editor if the text actually changed,
                    # and preserve the cursor so typing doesn't get wrecked.
                    # Also skip update if inline canvas editor is active on this item.
                    inline_editing_this = self._is_inline_editing_item(item)
                    old_text = self.txt_content.toPlainText()
                    if old_text != text and not inline_editing_this:
                        prev_block = self.txt_content.blockSignals(True)

                        cursor = self.txt_content.textCursor()
                        old_pos = cursor.position()

                        self.txt_content.setPlainText(text)

                        # Clamp cursor so we don't go out of range if text got shorter
                        new_len = len(text)
                        new_pos = min(old_pos, new_len)
                        cursor = self.txt_content.textCursor()
                        cursor.setPosition(new_pos)
                        self.txt_content.setTextCursor(cursor)

                        self.txt_content.blockSignals(prev_block)

                    f = QtGui.QFont(font_family)
                    self.font_combo.setCurrentFont(f)
                    self.spin_font_size.setValue(font_pt)
                    self.chk_bold.setChecked(bold)
                    self.chk_italic.setChecked(italic)

                    self.combo_h_align.setCurrentText(
                        "Left" if h_align == "left" else
                        "Center" if h_align == "center" else
                        "Right"
                    )
                    self.combo_v_align.setCurrentText(
                        "Top" if v_align == "top" else
                        "Middle" if v_align == "middle" else
                        "Bottom"
                    )

                    self.combo_wrap.setCurrentText(
                        "Word wrap" if wrap_mode == "word" else "Anywhere"
                    )
                    self.chk_shrink.setChecked(shrink)
                    self.spin_max_lines.setValue(max_lines)

                    self.lbl_bc_error.hide()
                    return

                # --- BARCODE MODE ---
                if kind == "barcode":
                    self._mode = "barcode"
                    self._current_item = item
                    self._current_elem = elem

                    self.lbl_target.setText("Barcode")
                    self._set_active(True)

                    # show barcode + layout; hide text/font/wrap/shape
                    self.grp_barcode.setVisible(True)
                    self.grp_layout.setVisible(True)
                    self.grp_text.setVisible(False)
                    self.grp_font.setVisible(False)
                    self.grp_align.setVisible(False)
                    self.grp_wrap.setVisible(False)
                    self.grp_padding.setVisible(False)
                    self.grp_shape.setVisible(False)

                    self._set_layout_enabled(True, True, True, True)

                    # Geometry (px → mm)
                    x_px = float(getattr(elem, "x", 0.0))
                    y_px = float(getattr(elem, "y", 0.0))
                    w_px = float(getattr(elem, "w", 40.0))
                    h_px = float(getattr(elem, "h", 20.0))

                    self.sp_x.setValue(self._px_to_mm(x_px))
                    self.sp_y.setValue(self._px_to_mm(y_px))
                    self.sp_w.setValue(self._px_to_mm(w_px))
                    self.sp_h.setValue(self._px_to_mm(h_px))

                    # type + data
                    bc_type = getattr(elem, "bc_type", "Code128")
                    data = getattr(elem, "text", "") or ""

                    idx = self.combo_bc_type.findText(
                        bc_type,
                        QtCore.Qt.MatchFlag.MatchFixedString,
                    )
                    if idx >= 0:
                        self.combo_bc_type.setCurrentIndex(idx)
                    else:
                        self.combo_bc_type.setCurrentText(bc_type)

                    self.edit_bc_data.setText(data)

                    # HRT properties
                    hr_pos = getattr(elem, "bc_hr_pos", "below") or "below"
                    hr_pos_l = hr_pos.lower()
                    if hr_pos_l.startswith("above"):
                        self.combo_bc_hr_pos.setCurrentText("Above")
                    elif hr_pos_l.startswith("none"):
                        self.combo_bc_hr_pos.setCurrentText("None")
                    else:
                        self.combo_bc_hr_pos.setCurrentText("Below")

                    hr_family = getattr(elem, "bc_hr_font_family", "Arial")
                    hr_size = int(getattr(elem, "bc_hr_font_point", 10) or 10)
                    self.font_bc.setCurrentFont(QtGui.QFont(hr_family))
                    self.spin_bc_font_size.setValue(hr_size)

                    self._refresh_barcode_error()
                    return

                # --- IMAGE MODE ---
                if kind == "image":
                    self._mode = "image"
                    self._current_item = item
                    self._current_elem = elem

                    self.lbl_target.setText("Image")
                    self._set_active(True)

                    # Only layout visible for now
                    self.grp_text.setVisible(False)
                    self.grp_font.setVisible(False)
                    self.grp_align.setVisible(False)
                    self.grp_wrap.setVisible(False)
                    self.grp_padding.setVisible(False)
                    self.grp_barcode.setVisible(False)
                    self.grp_shape.setVisible(False)
                    self.grp_layout.setVisible(True)

                    self._set_layout_enabled(True, True, True, True)

                    # Geometry from elem (same as text/barcode)
                    x_px = float(getattr(elem, "x", 0.0))
                    y_px = float(getattr(elem, "y", 0.0))
                    w_px = float(getattr(elem, "w", 40.0))
                    h_px = float(getattr(elem, "h", 20.0))

                    self.sp_x.setValue(self._px_to_mm(x_px))
                    self.sp_y.setValue(self._px_to_mm(y_px))
                    self.sp_w.setValue(self._px_to_mm(w_px))
                    self.sp_h.setValue(self._px_to_mm(h_px))

                    self.lbl_bc_error.hide()
                    return

                # Unsupported GItem kind → blank
                self.lbl_target.setText("")
                self._set_active(False)
                self.lbl_bc_error.hide()
                return

            # --- RECTANGLE ---
            if isinstance(item, GRectItem):
                self._mode = "rect"
                self._current_item = item
                self._current_elem = None

                self.lbl_target.setText("Rectangle")
                self._set_active(True)

                self.grp_text.setVisible(False)
                self.grp_font.setVisible(False)
                self.grp_align.setVisible(False)
                self.grp_wrap.setVisible(False)
                self.grp_padding.setVisible(False)
                self.grp_layout.setVisible(True)
                self.grp_barcode.setVisible(False)
                self.grp_shape.setVisible(True)

                self._set_layout_enabled(True, True, True, True)

                pos = item.pos()
                rect = item.rect()
                self.sp_x.setValue(self._px_to_mm(pos.x()))
                self.sp_y.setValue(self._px_to_mm(pos.y()))
                self.sp_w.setValue(self._px_to_mm(rect.width()))
                self.sp_h.setValue(self._px_to_mm(rect.height()))

                _fill_stroke_from_pen(item.pen())

                radius_px = float(getattr(item, "corner_radius_px", 0.0) or 0.0)
                radius_mm = self._px_to_mm(radius_px)
                self.spin_corner_radius.setEnabled(True)
                self.spin_corner_radius.setValue(radius_mm)

                pill = bool(getattr(item, "pill_mode", False))
                self.chk_pill.setEnabled(True)
                self.chk_pill.setChecked(pill)

                self.spin_star_points.setEnabled(False)
                self.spin_circle_diam.setEnabled(False)
                self.combo_arrow_side.setEnabled(False)
                self.spin_arrow_len.setEnabled(False)
                self.spin_arrow_width.setEnabled(False)
                return

            # --- DIAMOND ---
            if isinstance(item, GDiamondItem):
                self._mode = "diamond"
                self._current_item = item
                self._current_elem = None

                self.lbl_target.setText("Diamond")
                self._set_active(True)

                self.grp_text.setVisible(False)
                self.grp_font.setVisible(False)
                self.grp_align.setVisible(False)
                self.grp_wrap.setVisible(False)
                self.grp_padding.setVisible(False)
                self.grp_layout.setVisible(True)
                self.grp_barcode.setVisible(False)
                self.grp_shape.setVisible(True)

                self._set_layout_enabled(True, True, True, True)

                pos = item.pos()
                rect = item.rect()
                self.sp_x.setValue(self._px_to_mm(pos.x()))
                self.sp_y.setValue(self._px_to_mm(pos.y()))
                self.sp_w.setValue(self._px_to_mm(rect.width()))
                self.sp_h.setValue(self._px_to_mm(rect.height()))

                _fill_stroke_from_pen(item.pen())

                # No rounded corners or pill mode for diamonds
                self.spin_corner_radius.setEnabled(False)
                self.chk_pill.setEnabled(False)
                self.spin_star_points.setEnabled(False)
                self.spin_circle_diam.setEnabled(False)
                self.combo_arrow_side.setEnabled(False)
                self.spin_arrow_len.setEnabled(False)
                self.spin_arrow_width.setEnabled(False)
                return

            # --- CIRCLE (ellipse-as-circle) ---
            if isinstance(item, GEllipseItem):
                self._mode = "circle"
                self._current_item = item
                self._current_elem = None

                self.lbl_target.setText("Circle")
                self._set_active(True)

                self.grp_text.setVisible(False)
                self.grp_font.setVisible(False)
                self.grp_align.setVisible(False)
                self.grp_wrap.setVisible(False)
                self.grp_padding.setVisible(False)
                self.grp_layout.setVisible(True)
                self.grp_barcode.setVisible(False)
                self.grp_shape.setVisible(True)

                self._set_layout_enabled(True, True, False, False)

                pos = item.pos()
                rect = item.rect()
                self.sp_x.setValue(self._px_to_mm(pos.x()))
                self.sp_y.setValue(self._px_to_mm(pos.y()))

                diam_px = max(rect.width(), rect.height())
                diam_mm = self._px_to_mm(diam_px)

                self.spin_circle_diam.setEnabled(True)
                self.spin_circle_diam.setValue(diam_mm)
                self.sp_w.setValue(diam_mm)
                self.sp_h.setValue(diam_mm)

                _fill_stroke_from_pen(item.pen())

                self.spin_star_points.setEnabled(False)
                self.spin_corner_radius.setEnabled(False)
                self.chk_pill.setEnabled(False)
                self.combo_arrow_side.setEnabled(False)
                self.spin_arrow_len.setEnabled(False)
                self.spin_arrow_width.setEnabled(False)
                return

            # --- STAR ---
            if isinstance(item, GStarItem):
                self._mode = "star"
                self._current_item = item
                self._current_elem = None

                self.lbl_target.setText("Star")
                self._set_active(True)

                self.grp_text.setVisible(False)
                self.grp_font.setVisible(False)
                self.grp_align.setVisible(False)
                self.grp_wrap.setVisible(False)
                self.grp_padding.setVisible(False)
                self.grp_layout.setVisible(True)
                self.grp_barcode.setVisible(False)
                self.grp_shape.setVisible(True)

                self._set_layout_enabled(True, True, True, True)

                pos = item.pos()
                rect = item.rect()
                self.sp_x.setValue(self._px_to_mm(pos.x()))
                self.sp_y.setValue(self._px_to_mm(pos.y()))
                self.sp_w.setValue(self._px_to_mm(rect.width()))
                self.sp_h.setValue(self._px_to_mm(rect.height()))

                _fill_stroke_from_pen(item.pen())

                pts = int(getattr(item, "star_points", 5) or 5)
                pts = max(3, pts)
                self.spin_star_points.setEnabled(True)
                self.spin_star_points.setValue(pts)

                self.spin_circle_diam.setEnabled(False)
                self.spin_corner_radius.setEnabled(False)
                self.chk_pill.setEnabled(False)
                self.combo_arrow_side.setEnabled(False)
                self.spin_arrow_len.setEnabled(False)
                self.spin_arrow_width.setEnabled(False)
                return

            # --- ARROW (must be BEFORE plain GLineItem) ---
            if isinstance(item, GArrowItem):
                self._mode = "arrow"
                self._current_item = item
                self._current_elem = None

                self.lbl_target.setText("Arrow")
                self._set_active(True)

                self.grp_text.setVisible(False)
                self.grp_font.setVisible(False)
                self.grp_align.setVisible(False)
                self.grp_wrap.setVisible(False)
                self.grp_padding.setVisible(False)
                self.grp_layout.setVisible(False)
                self.grp_barcode.setVisible(False)
                self.grp_shape.setVisible(True)

                _fill_stroke_from_pen(item.pen())

                at_start = bool(getattr(item, "arrow_at_start", False))
                self.combo_arrow_side.setEnabled(True)
                self.combo_arrow_side.setCurrentText(
                    "Start (←)" if at_start else "End (→)"
                )

                length_px = float(getattr(item, "arrow_length_px", 10.0) or 10.0)
                width_px = float(getattr(item, "arrow_width_px", 6.0) or 6.0)
                self.spin_arrow_len.setEnabled(True)
                self.spin_arrow_len.setValue(self._px_to_mm(length_px))
                self.spin_arrow_width.setEnabled(True)
                self.spin_arrow_width.setValue(self._px_to_mm(width_px))

                self.spin_star_points.setEnabled(False)
                self.spin_circle_diam.setEnabled(False)
                self.spin_corner_radius.setEnabled(False)
                self.chk_pill.setEnabled(False)
                return

            # --- LINE (plain GLineItem, NOT arrow) ---
            if isinstance(item, GLineItem) and not isinstance(item, GArrowItem):
                self._mode = "line"
                self._current_item = item
                self._current_elem = None

                self.lbl_target.setText("Line")
                self._set_active(True)

                self.grp_text.setVisible(False)
                self.grp_font.setVisible(False)
                self.grp_align.setVisible(False)
                self.grp_wrap.setVisible(False)
                self.grp_padding.setVisible(False)
                self.grp_layout.setVisible(False)
                self.grp_barcode.setVisible(False)
                self.grp_shape.setVisible(True)

                _fill_stroke_from_pen(item.pen())

                self.spin_star_points.setEnabled(False)
                self.spin_circle_diam.setEnabled(False)
                self.spin_corner_radius.setEnabled(False)
                self.chk_pill.setEnabled(False)
                self.combo_arrow_side.setEnabled(False)
                self.spin_arrow_len.setEnabled(False)
                self.spin_arrow_width.setEnabled(False)
                return

            # Fallback
            self.lbl_target.setText("")
            self._set_active(False)
            self.lbl_bc_error.hide()

        finally:
            self._updating_ui = False

    # --------------------- external sync helper ---------------------

    def refresh_geometry_from_model(self):
        """
        Called by MainWindow when the scene geometry changes externally
        (e.g. drag-resize on canvas). Keeps the spinboxes in sync.
        """
        if self._current_item is None:
            return

        self._updating_ui = True
        try:
            it = self._current_item

            # TEXT / BARCODE: read from elem
            if self._mode in ("text", "barcode", "image") and self._current_elem is not None:
                e = self._current_elem
                self.sp_x.setValue(self._px_to_mm(float(getattr(e, "x", 0.0))))
                self.sp_y.setValue(self._px_to_mm(float(getattr(e, "y", 0.0))))
                self.sp_w.setValue(self._px_to_mm(float(getattr(e, "w", 0.0))))
                self.sp_h.setValue(self._px_to_mm(float(getattr(e, "h", 0.0))))
                return

            # RECT / STAR / CIRCLE: read from item
            if self._mode in ("rect", "star", "circle", "diamond") and isinstance(
                it, QtWidgets.QGraphicsRectItem
            ):
                pos = it.pos()
                rect = it.rect()
                self.sp_x.setValue(self._px_to_mm(pos.x()))
                self.sp_y.setValue(self._px_to_mm(pos.y()))
                self.sp_w.setValue(self._px_to_mm(rect.width()))
                self.sp_h.setValue(self._px_to_mm(rect.height()))

                if self._mode == "circle":
                    diam_px = max(rect.width(), rect.height())
                    self.spin_circle_diam.setValue(self._px_to_mm(diam_px))
                return

        finally:
            self._updating_ui = False

    # --------------------- touch & geometry ---------------------

    def _touch_item(self):
        if self._current_item is None:
            return
        # bust cache if GItem
        if hasattr(self._current_item, "_cache_qimage"):
            self._current_item._cache_qimage = None
        if hasattr(self._current_item, "_cache_key"):
            self._current_item._cache_key = None
        self._current_item.update()
        self.element_changed.emit()

    def _on_geom_changed(self):
        if self._updating_ui:
            return
        if self._current_item is None:
            return

        x_mm = self.sp_x.value()
        y_mm = self.sp_y.value()
        w_mm = self.sp_w.value()
        h_mm = self.sp_h.value()

        x_px = self._mm_to_px(x_mm)
        y_px = self._mm_to_px(y_mm)
        w_px = self._mm_to_px(w_mm)
        h_px = self._mm_to_px(h_mm)

        # If we have an undo stack and a rect-based item, use MoveResizeCmd
        if (
            self._undo_stack is not None
            and isinstance(self._current_item, QtWidgets.QGraphicsRectItem)
        ):
            old_pos = QtCore.QPointF(self._current_item.pos())
            old_rect = QtCore.QRectF(self._current_item.rect())

            new_pos = QtCore.QPointF(x_px, y_px)
            new_rect = QtCore.QRectF(0, 0, w_px, h_px)

            if old_pos == new_pos and old_rect == new_rect:
                return

            cmd = MoveResizeCmd(
                self._current_item,
                old_pos,
                old_rect,
                new_pos,
                new_rect,
                text="Change geometry",
            )
            self._undo_stack.push(cmd)
            self.element_changed.emit()
            return

        # Fallback: apply directly (no undo stack configured)

        # TEXT / BARCODE (GItem) → update elem + item
        if self._mode in ("text", "barcode") and self._current_elem is not None and isinstance(
            self._current_item, GItem
        ):
            self._current_elem.x = float(x_px)
            self._current_elem.y = float(y_px)
            self._current_elem.w = float(w_px)
            self._current_elem.h = float(h_px)

            self._current_item.setPos(x_px, y_px)
            self._current_item.setRect(0, 0, w_px, h_px)
            self._touch_item()
            return

        # RECT / STAR / CIRCLE use QGraphicsRectItem geometry
        if self._mode in ("rect", "star", "circle", "diamond") and isinstance(
            self._current_item, QtWidgets.QGraphicsRectItem
        ):
            self._current_item.setPos(x_px, y_px)
            if self._mode == "circle":
                # keep it square; diameter is in spin_circle_diam
                diam_mm = self.spin_circle_diam.value()
                d_px = self._mm_to_px(diam_mm)
                self._current_item.setRect(0, 0, d_px, d_px)
            else:
                self._current_item.setRect(0, 0, w_px, h_px)
            self._touch_item()

    # --------------------- text slots ---------------------

    def _on_text_changed(self):
        """Handle text content changes with undo buffering"""
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        
        # First edit on this item - store original value
        if self._pending_text_item != self._current_item:
            # Commit any pending changes from previous item
            if self._pending_text_item is not None:
                self._commit_text_to_undo()
            
            self._pending_text_item = self._current_item
            self._pending_text_old_value = self._current_elem.text
        
        # Update element immediately (live preview)
        new_text = self.txt_content.toPlainText()
        self._current_elem.text = new_text
        if self._current_item:
            self._current_item.update()  # Refresh the visual
        
        # Restart the undo timer - will commit after 1 second of no typing
        self._text_undo_timer.stop()
        self._text_undo_timer.start()

    def _commit_text_to_undo(self):
        """Commit accumulated text changes to undo stack"""
        if self._pending_text_item is None:
            return
        
        # Get current value
        if self._pending_text_item == self._current_item and self._current_elem:
            new_value = self._current_elem.text
        else:
            new_value = self._pending_text_item.elem.text if hasattr(self._pending_text_item, 'elem') else ""
        
        old_value = self._pending_text_old_value
        
        # Only create undo command if text actually changed
        if new_value != old_value:
            elem = self._pending_text_item.elem if hasattr(self._pending_text_item, 'elem') else self._current_elem
            if elem:
                cmd = PropertyChangeCmd(
                    elem,
                    "text",
                    old_value,
                    new_value,
                    "Change text",           # ← 5th param: text (description)
                    self._pending_text_item  # ← 6th param: item
                )
                if self._undo_stack:
                    self._undo_stack.push(cmd)
        
        # Clear pending state
        self._pending_text_item = None
        self._pending_text_old_value = None

    def _commit_font_size_to_undo(self):
        """Commit font size change to undo stack"""
        if self._pending_font_size_item is None:
            return
        
        # Get current value
        if self._pending_font_size_item == self._current_item and self._current_elem:
            new_value = self._current_elem.font_point
        else:
            new_value = self._pending_font_size_item.elem.font_point if hasattr(self._pending_font_size_item, 'elem') else 12
        
        old_value = self._pending_font_size_old_value
        
        # Only create undo command if value actually changed
        if new_value != old_value:
            elem = self._pending_font_size_item.elem if hasattr(self._pending_font_size_item, 'elem') else self._current_elem
            if elem:
                cmd = PropertyChangeCmd(
                    elem,
                    "font_point",
                    old_value,
                    new_value,
                    "Change font size",           # ← 5th param: text (description)
                    self._pending_font_size_item  # ← 6th param: item
                )
                if self._undo_stack:
                    self._undo_stack.push(cmd)
        
        # Clear pending state
        self._pending_font_size_item = None
        self._pending_font_size_old_value = None

    def _on_font_changed(self, qfont: QtGui.QFont):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        self._push_elem_property(
            "font_family",
            qfont.family(),
            "Change font family",
        )

    def _on_font_size_changed(self, value: int):
        """Buffer font size changes"""
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        
        v = int(value)
        
        # ========== Patch 8: Buffer font size changes ==========
        # First edit on this item - store original value
        if self._pending_font_size_item != self._current_item:
            if self._pending_font_size_item is not None:
                self._commit_font_size_to_undo()
            self._pending_font_size_item = self._current_item
            self._pending_font_size_old_value = getattr(self._current_elem, "font_point", 12)
        
        # Update element immediately (live preview)
        # main one used by painter/cache/UI
        self._current_elem.font_point = v
        
        # keep legacy font_size in sync without clogging undo
        setattr(self._current_elem, "font_size", v)
        
        # Update visual
        if self._current_item:
            self._current_item.update()
        
        # Restart timer - will commit to undo after 500ms of no changes
        self._font_size_undo_timer.stop()
        self._font_size_undo_timer.start()
        # ========== END Patch 8 ==========

    def _on_bold_toggled(self, checked: bool):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        self._push_elem_property(
            "bold",
            bool(checked),
            "Toggle bold",
        )

    def _on_italic_toggled(self, checked: bool):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        self._push_elem_property(
            "italic",
            bool(checked),
            "Toggle italic",
        )

    def _on_h_align_changed(self, text: str):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        text_l = (text or "").lower()
        if text_l.startswith("left"):
            val = "left"
        elif text_l.startswith("center"):
            val = "center"
        elif text_l.startswith("right"):
            val = "right"
        else:
            val = "left"
        self._push_elem_property("h_align", val, "Change horizontal alignment")

    def _on_v_align_changed(self, text: str):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        text_l = (text or "").lower()
        if text_l.startswith("top"):
            val = "top"
        elif text_l.startswith("middle"):
            val = "middle"
        elif text_l.startswith("bottom"):
            val = "bottom"
        else:
            val = "top"
        self._push_elem_property("v_align", val, "Change vertical alignment")

    def _on_wrap_mode_changed(self, text: str):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        text_l = (text or "").lower()
        val = "word" if text_l.startswith("word") else "anywhere"
        self._push_elem_property("wrap_mode", val, "Change wrap mode")

    def _on_shrink_toggled(self, checked: bool):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        self._push_elem_property(
            "shrink_to_fit",
            bool(checked),
            "Toggle shrink-to-fit",
        )

    def _on_max_lines_changed(self, val: int):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        self._push_elem_property(
            "max_lines",
            int(val),
            "Change max lines",
        )

    # --------------------- shape / stroke slots ---------------------

    def _on_line_width_changed(self, val: float):
        if self._updating_ui:
            return
        if self._mode not in ("line", "arrow", "rect", "circle", "star"):
            return
        it = self._current_item
        if it is None:
            return
        if not hasattr(it, "pen"):
            return
        pen = it.pen()
        pen.setWidthF(float(val))
        it.setPen(pen)
        self._touch_item()

    def _on_line_style_changed(self, text: str):
        if self._updating_ui:
            return
        if self._mode not in ("line", "arrow", "rect", "circle", "star"):
            return
        it = self._current_item
        if it is None or not hasattr(it, "pen"):
            return

        text_l = (text or "").lower()
        pen = it.pen()

        if text_l.startswith("solid"):
            pen.setStyle(QtCore.Qt.SolidLine)
            pen.setDashPattern([])
        elif text_l.startswith("dash-dot"):
            pen.setStyle(QtCore.Qt.DashDotLine)
            pen.setDashPattern([])
        elif text_l.startswith("dash"):
            pen.setStyle(QtCore.Qt.DashLine)
            pen.setDashPattern([])
        elif text_l.startswith("dot"):
            pen.setStyle(QtCore.Qt.DotLine)
            pen.setDashPattern([])
        elif text_l.startswith("perf"):  # Perforation
            pen.setStyle(QtCore.Qt.CustomDashLine)
            pen.setDashPattern([2.0, 4.0])
        else:
            pen.setStyle(QtCore.Qt.SolidLine)
            pen.setDashPattern([])

        it.setPen(pen)
        self._touch_item()

    def _on_star_points_changed(self, val: int):
        if self._updating_ui or self._mode != "star":
            return
        it = self._current_item
        if it is None or not isinstance(it, GStarItem):
            return
        pts = max(3, int(val))
        it.star_points = pts
        it.update()
        self._touch_item()

    def _on_circle_diameter_changed(self, val: float):
        if self._updating_ui or self._mode != "circle":
            return
        it = self._current_item
        if it is None or not isinstance(it, GEllipseItem):
            return

        d_px = self._mm_to_px(max(1.0, float(val)))

        # If we have undo stack, treat as MoveResizeCmd with same pos, new rect
        if self._undo_stack is not None:
            old_pos = QtCore.QPointF(it.pos())
            old_rect = QtCore.QRectF(it.rect())
            new_pos = QtCore.QPointF(old_pos)
            new_rect = QtCore.QRectF(0, 0, d_px, d_px)

            if old_rect == new_rect:
                return

            cmd = MoveResizeCmd(
                it,
                old_pos,
                old_rect,
                new_pos,
                new_rect,
                text="Change circle diameter",
            )
            self._undo_stack.push(cmd)
            self.element_changed.emit()
            return

        # Fallback: direct apply
        it.setRect(0, 0, d_px, d_px)
        self._touch_item()

    def _on_corner_radius_changed(self, val: float):
        if self._updating_ui or self._mode != "rect":
            return
        it = self._current_item
        if it is None or not isinstance(it, GRectItem):
            return
        radius_px = self._mm_to_px(max(0.0, float(val)))
        it.corner_radius_px = radius_px
        it.update()
        self._touch_item()

    def _on_pill_toggled(self, checked: bool):
        if self._updating_ui or self._mode != "rect":
            return
        it = self._current_item
        if it is None or not isinstance(it, GRectItem):
            return
        it.pill_mode = bool(checked)
        it.update()
        self._touch_item()

    # --------------------- arrow slots ---------------------

    def _on_arrow_side_changed(self, text: str):
        if self._updating_ui or self._mode != "arrow":
            return
        it = self._current_item
        if it is None or not isinstance(it, GArrowItem):
            return
        text_l = (text or "").lower()
        it.arrow_at_start = text_l.startswith("start")
        it.update()
        self._touch_item()

    def _on_arrow_len_changed(self, val: float):
        if self._updating_ui or self._mode != "arrow":
            return
        it = self._current_item
        if it is None or not isinstance(it, GArrowItem):
            return
        length_mm = max(0.5, float(val))
        length_px = self._mm_to_px(length_mm)
        it.arrow_length_px = length_px
        it.update()
        self._touch_item()

    def _on_arrow_width_changed(self, val: float):
        if self._updating_ui or self._mode != "arrow":
            return
        it = self._current_item
        if it is None or not isinstance(it, GArrowItem):
            return
        width_mm = max(0.5, float(val))
        width_px = self._mm_to_px(width_mm)
        it.arrow_width_px = width_px
        it.update()
        self._touch_item()

    # --------------------- slots: barcode ---------------------

    def _on_barcode_type_changed(self, label: str):
        if self._updating_ui:
            return
        if self._current_elem is None or self._mode != "barcode":
            return
        self._push_elem_property("bc_type", label, "Change barcode type")
        self._refresh_barcode_error()

    def _on_barcode_data_changed(self, text: str):
        if self._updating_ui:
            return
        if self._current_elem is None or self._mode != "barcode":
            return
        self._push_elem_property("text", text, "Change barcode data")
        self._refresh_barcode_error()

    def _on_barcode_hr_pos_changed(self, label: str):
        if self._updating_ui:
            return
        if self._current_elem is None or self._mode != "barcode":
            return
        label_l = (label or "").lower()
        if label_l.startswith("above"):
            val = "above"
        elif label_l.startswith("none"):
            val = "none"
        else:
            val = "below"
        self._push_elem_property("bc_hr_pos", val, "Change HRT position")

    def _on_barcode_hr_font_changed(self, qfont: QtGui.QFont):
        if self._updating_ui:
            return
        if self._current_elem is None or self._mode != "barcode":
            return
        self._push_elem_property(
            "bc_hr_font_family",
            qfont.family(),
            "Change HRT font",
        )

    def _on_barcode_hr_font_size_changed(self, val: int):
        if self._updating_ui:
            return
        if self._current_elem is None or self._mode != "barcode":
            return
        self._push_elem_property(
            "bc_hr_font_point",
            int(val),
            "Change HRT font size",
        )

    def _on_pad_left_changed(self, val: float):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        self._push_elem_property("pad_left", float(val), "Change left padding")

    def _on_pad_right_changed(self, val: float):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        self._push_elem_property("pad_right", float(val), "Change right padding")

    def _on_pad_top_changed(self, val: float):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        self._push_elem_property("pad_top", float(val), "Change top padding")

    def _on_pad_bottom_changed(self, val: float):
        if self._updating_ui or self._mode != "text":
            return
        if self._current_elem is None:
            return
        self._push_elem_property("pad_bottom", float(val), "Change bottom padding")

    def _refresh_barcode_error(self) -> None:
        """
        Validate current barcode data against the selected symbology.

        Uses the *barcode* data field.
        Skips validation if templated ({{...}}) data is present.
        """
        if not hasattr(self, "lbl_bc_error"):
            return

        if self._updating_ui or self._mode != "barcode" or self._current_elem is None:
            self.lbl_bc_error.hide()
            return

        # Use the barcode-specific widgets, not the text content editor
        txt = (self.edit_bc_data.text() or "").strip()
        bc_kind = self.combo_bc_type.currentText() or "Code128"

        # If using {{date}} or other variable placeholders, don't hard-fail here
        if "{{" in txt or "}}" in txt:
            self.lbl_bc_error.hide()
            return

        try:
            validate_barcode_data(bc_kind, txt)
        except BarcodeValidationError as exc:
            self.lbl_bc_error.setText(str(exc))
            self.lbl_bc_error.show()
        else:
            self.lbl_bc_error.hide()
