from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets

try:
    from PySide6.QtSvgWidgets import QSvgRenderer
except Exception:  # if QtSvg isn’t installed, SVG just won’t render
    QSvgRenderer = None

from ..core.models import Element, GuideGrid, GuideLine
from ..core.barcodes import render_barcode_to_qimage, validate_barcode_data, BarcodeValidationError

from .views import PX_PER_MM
from ..core.commands import MoveResizeCmd, MoveLineCmd, ResizeLineCmd

import datetime
import os
import math
import re

class ContextMenuMixin:
    """
    Mixin that adds a right-click context menu to scene items.

    It delegates actions back to the MainWindow, which already has:
    - _duplicate_selected_items
    - _change_z_order(mode)
    - _lock_selected / _unlock_selected
    - _hide_selected
    - _delete_selected_items
    """

    def _resolve_main_window(self):
        scene = self.scene()
        if scene is None:
            return None
        views = scene.views()
        if not views:
            return None
        win = views[0].window()
        return win

    def contextMenuEvent(self, event: QtWidgets.QGraphicsSceneContextMenuEvent) -> None:
        win = self._resolve_main_window()
        scene = self.scene()
        if scene is None or win is None:
            return

        # Make sure the item we right-clicked is part of the selection
        if not self.isSelected():
            scene.clearSelection()
            self.setSelected(True)

        menu = QtWidgets.QMenu()

        act_dup = menu.addAction("Duplicate")
        menu.addSeparator()

        act_front = menu.addAction("Bring to Front")
        act_back = menu.addAction("Send to Back")
        act_up = menu.addAction("Bring Forward")
        act_down = menu.addAction("Send Backward")

        menu.addSeparator()
        is_locked = (self.data(0) == "locked")
        act_lock = menu.addAction("Unlock" if is_locked else "Lock")
        act_hide = menu.addAction("Hide")

        menu.addSeparator()
        act_delete = menu.addAction("Delete")

        chosen = menu.exec(event.screenPos())
        if not chosen:
            return

        # Use MainWindow helpers so behavior matches toolbar / shortcuts
        if chosen == act_dup and hasattr(win, "_duplicate_selected_items"):
            win._duplicate_selected_items()

        elif chosen == act_front and hasattr(win, "_change_z_order"):
            win._change_z_order("front")
        elif chosen == act_back and hasattr(win, "_change_z_order"):
            win._change_z_order("back")
        elif chosen == act_up and hasattr(win, "_change_z_order"):
            win._change_z_order("up")
        elif chosen == act_down and hasattr(win, "_change_z_order"):
            win._change_z_order("down")

        elif chosen == act_lock:
            if is_locked and hasattr(win, "_unlock_selected"):
                win._unlock_selected()
            elif not is_locked and hasattr(win, "_lock_selected"):
                win._lock_selected()

        elif chosen == act_hide and hasattr(win, "_hide_selected"):
            win._hide_selected()

        elif chosen == act_delete and hasattr(win, "_delete_selected_items"):
            win._delete_selected_items()


class GItem(ContextMenuMixin, QtWidgets.QGraphicsRectItem):
    HANDLE_SZ = 10

    def __init__(self, elem: Element):
        super().__init__(
            0,
            0,
            float(getattr(elem, "w", 160.0)),
            float(getattr(elem, "h", 40.0)),
        )
        self.elem = elem

        self.setFlags(
            QtWidgets.QGraphicsItem.ItemIsMovable
            | QtWidgets.QGraphicsItem.ItemIsSelectable
            | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)

        # QUndoStack reference (set by MainWindow when creating/loading items)
        self.undo_stack = None

        self._resizing = False
        self._cache_qimage: QtGui.QImage | None = None
        self._cache_key = None

        # last geometry (can be useful later for sync, etc.)
        self._last_pos = QtCore.QPointF(
            float(getattr(elem, "x", 0.0)),
            float(getattr(elem, "y", 0.0)),
        )
        self._last_rect = QtCore.QRectF(0, 0, self.rect().width(), self.rect().height())

        # starting geometry for move/resize undo
        self._move_start_pos: QtCore.QPointF | None = None
        self._move_start_rect: QtCore.QRectF | None = None

        self.setPen(QtCore.Qt.NoPen)
        self.setBrush(QtCore.Qt.NoBrush)

    # ---------- geometry helpers ----------
    def _handle_rect(self) -> QtCore.QRectF:
        r = self.rect()
        return QtCore.QRectF(
            r.right() - self.HANDLE_SZ,
            r.bottom() - self.HANDLE_SZ,
            self.HANDLE_SZ,
            self.HANDLE_SZ,
        )

    # ---------- text helpers ----------
    def _resolve_text(self, text: str) -> str:
        """
        Expand simple template variables inside text.

        Supported:
          {{date}}                          -> YYYY-MM-DD
          {{date:%m/%d/%Y}}                -> custom date format
          {{time}}                          -> HH:MM (24h)
          {{time:%I:%M %p}}                -> custom time format
          {{datetime}}                      -> YYYY-MM-DD HH:MM
          {{datetime:%b %d, %Y %I:%M %p}}  -> custom datetime format
          {{id}}                            -> simple placeholder (TEST-001 for now)

        Formatting codes are standard Python datetime.strftime tokens.
        (We no longer add any custom %d/%dd/%mmm sugar.)
        """
        if not text:
            return ""

        now = datetime.datetime.now()

        # Regex for {{date:...}}, {{time:...}}, {{datetime:...}}
        pattern = re.compile(r"\{\{(date|time|datetime)(?::([^}]+))?\}\}")

        def _safe_strftime(dt: datetime.datetime, fmt: str, kind: str) -> str:
            """Call strftime but never let a bad format crash the app."""
            try:
                return dt.strftime(fmt)
            except Exception:
                if kind == "date":
                    return dt.strftime("%Y-%m-%d")
                elif kind == "time":
                    return dt.strftime("%H:%M")
                elif kind == "datetime":
                    return dt.strftime("%Y-%m-%d %H:%M")
                return dt.isoformat(sep=" ", timespec="minutes")

        def _replace_match(m: re.Match) -> str:
            kind = m.group(1)
            fmt = (m.group(2) or "").strip()

            if kind == "date":
                fmt = fmt or "%Y-%m-%d"
                return _safe_strftime(now, fmt, "date")
            elif kind == "time":
                fmt = fmt or "%H:%M"
                return _safe_strftime(now, fmt, "time")
            elif kind == "datetime":
                fmt = fmt or "%Y-%m-%d %H:%M"
                return _safe_strftime(now, fmt, "datetime")

            # just in case, fall back to original text
            return m.group(0)

        # First, handle date/time/datetime (with or without format)
        text = pattern.sub(_replace_match, text)

        # Then, simple non-formatted placeholders (back-compat)
        replacements = {
            "{{date}}": now.strftime("%Y-%m-%d"),
            "{{time}}": now.strftime("%H:%M"),
            "{{datetime}}": now.strftime("%Y-%m-%d %H:%M"),
            "{{id}}": "TEST-001",   # TODO: real IDs later
        }
        for k, v in replacements.items():
            text = text.replace(k, v)

        return text



    def _paint_text(self, painter: QtGui.QPainter, w: int, h: int) -> None:
        # pull properties with safe defaults
        text = self._resolve_text(getattr(self.elem, "text", "") or "")
        family = getattr(self.elem, "font_family", "Arial")

        # 👇 NEW: honor font_size first, fall back to font_point
        # Prefer font_point (used by the Properties panel); fall back to legacy font_size
        size = getattr(self.elem, "font_point", None)
        if size is None:
            size = getattr(self.elem, "font_size", 12)
        try:
            size = int(size or 12)
        except Exception:
            size = 12


        bold = bool(getattr(self.elem, "bold", False))
        italic = bool(getattr(self.elem, "italic", False))
        h_align = getattr(self.elem, "h_align", "left")
        v_align = getattr(self.elem, "v_align", "top")
        wrap_mode = getattr(self.elem, "wrap_mode", "word")
        shrink = bool(getattr(self.elem, "shrink_to_fit", False))
        max_lines = int(getattr(self.elem, "max_lines", 0) or 0)

        # padding in px
        pad_left = float(getattr(self.elem, "pad_left", 0.0) or 0.0)
        pad_right = float(getattr(self.elem, "pad_right", 0.0) or 0.0)
        pad_top = float(getattr(self.elem, "pad_top", 0.0) or 0.0)
        pad_bottom = float(getattr(self.elem, "pad_bottom", 0.0) or 0.0)

        # clamp so we don't go negative
        pad_left = max(0.0, pad_left)
        pad_right = max(0.0, pad_right)
        pad_top = max(0.0, pad_top)
        pad_bottom = max(0.0, pad_bottom)

        inner_w = max(1.0, w - pad_left - pad_right)
        inner_h = max(1.0, h - pad_top - pad_bottom)
        inner_x = pad_left
        inner_y = pad_top

        f = QtGui.QFont(family, size)
        f.setBold(bold)
        f.setItalic(italic)

        # base flags from align + wrap
        flags = QtCore.Qt.AlignmentFlag(0)

        if h_align == "left":
            flags |= QtCore.Qt.AlignLeft
        elif h_align == "center":
            flags |= QtCore.Qt.AlignHCenter
        elif h_align == "right":
            flags |= QtCore.Qt.AlignRight
        else:
            flags |= QtCore.Qt.AlignLeft

        if v_align == "top":
            flags |= QtCore.Qt.AlignTop
        elif v_align == "middle":
            flags |= QtCore.Qt.AlignVCenter
        elif v_align == "bottom":
            flags |= QtCore.Qt.AlignBottom
        else:
            flags |= QtCore.Qt.AlignTop

        wrap_flag = (
            QtCore.Qt.TextWordWrap if wrap_mode == "word" else QtCore.Qt.TextWrapAnywhere
        )
        flags |= wrap_flag

        # shrink-to-fit: binary search font size down if needed, using inner rect
        if shrink and size > 5:
            fm = QtGui.QFontMetrics(f)
            test_rect = QtCore.QRect(0, 0, int(inner_w), int(inner_h * 10))
            r = fm.boundingRect(test_rect, int(flags), text)
            if r.width() > inner_w or r.height() > inner_h:
                min_pt, max_pt, final_pt = 4, size, size
                while min_pt <= max_pt:
                    mid_pt = (min_pt + max_pt) // 2
                    f.setPointSize(mid_pt)
                    fm = QtGui.QFontMetrics(f)
                    r = fm.boundingRect(test_rect, int(flags), text)
                    if r.width() <= inner_w and r.height() <= inner_h:
                        final_pt = mid_pt
                        min_pt = mid_pt + 1
                    else:
                        max_pt = mid_pt - 1
                f.setPointSize(max(4, final_pt))

        painter.setFont(f)
        painter.setPen(QtCore.Qt.black)

        # If a max_lines cap is set, use QTextLayout with manual line control
        if max_lines > 0:
            layout = QtGui.QTextLayout(text, f)
            opt = QtGui.QTextOption()
            opt.setWrapMode(
                QtGui.QTextOption.WrapMode.WordWrap
                if wrap_mode == "word"
                else QtGui.QTextOption.WrapAnywhere
            )
            if h_align == "center":
                opt.setAlignment(QtCore.Qt.AlignHCenter)
            elif h_align == "right":
                opt.setAlignment(QtCore.Qt.AlignRight)
            layout.setTextOption(opt)

            layout.beginLayout()
            lines = []
            y = 0.0
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(inner_w)
                if y + line.height() > inner_h or len(lines) >= max_lines:
                    break
                lines.append(line)
                y += line.height()
            layout.endLayout()

            total_height = sum(l.height() for l in lines) if lines else 0.0
            y_offset = 0.0
            if v_align == "middle":
                y_offset = (inner_h - total_height) / 2.0
            elif v_align == "bottom":
                y_offset = inner_h - total_height

            base = QtCore.QPointF(inner_x, inner_y + y_offset)
            for i, line in enumerate(lines):
                line.draw(painter, base + QtCore.QPointF(0, i * line.height()))
        else:
            # simple drawText into the padded rect
            painter.drawText(
                QtCore.QRectF(inner_x, inner_y, inner_w, inner_h),
                int(flags),
                text,
            )

    def _paint_barcode(self, painter: QtGui.QPainter, w: int, h: int) -> None:
        from ..core.barcodes import render_barcode_to_qimage

        # Barcode type + data
        bc_type = getattr(self.elem, "bc_type", "Code128")
        raw_text = getattr(self.elem, "text", "") or ""
        data = self._resolve_text(raw_text) or " "

        img = render_barcode_to_qimage(bc_type, data)
        if img.isNull():
            return

        # Human-readable text settings
        hr_pos = getattr(self.elem, "bc_hr_pos", "below") or "below"
        hr_pos = hr_pos.lower()
        hr_family = getattr(self.elem, "bc_hr_font_family", "Arial")
        hr_size = int(getattr(self.elem, "bc_hr_font_point", 10) or 10)

        # Bars should be crisp, but we still want decent scaling
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)

        padding = 2
        bar_rect = QtCore.QRectF(0, 0, w, h)
        text_rect: QtCore.QRectF | None = None

        text_height = 0
        if hr_pos != "none":
            font = QtGui.QFont(hr_family, hr_size)
            fm = QtGui.QFontMetrics(font)
            text_height = fm.height()

            # Don’t let the text region be microscopic or bigger than the box
            text_height = max(8, min(text_height, max(0, h - 4)))

            if hr_pos.startswith("above"):
                text_rect = QtCore.QRectF(0, 0, w, text_height)
                bar_rect = QtCore.QRectF(
                    0,
                    text_height + padding,
                    w,
                    max(4, h - text_height - padding),
                )
            else:  # "below" default
                bar_rect = QtCore.QRectF(
                    0,
                    0,
                    w,
                    max(4, h - text_height - padding),
                )
                text_rect = QtCore.QRectF(
                    0,
                    bar_rect.bottom() + padding,
                    w,
                    text_height,
                )

        # Always start with a white background in the whole item rect
        painter.fillRect(QtCore.QRectF(0, 0, w, h), QtCore.Qt.white)

        # --- draw barcode image into bar_rect (centered, keep aspect ratio) ---
        src_rect = img.rect()
        if bar_rect.width() > 0 and bar_rect.height() > 0:
            src_ratio = src_rect.width() / src_rect.height() if src_rect.height() else 1.0
            dst_ratio = bar_rect.width() / bar_rect.height() if bar_rect.height() else 1.0

            if dst_ratio > src_ratio:
                # Fit by height
                target_h = bar_rect.height()
                target_w = target_h * src_ratio
            else:
                # Fit by width
                target_w = bar_rect.width()
                target_h = target_w / src_ratio

            tx = bar_rect.x() + (bar_rect.width() - target_w) / 2.0
            ty = bar_rect.y() + (bar_rect.height() - target_h) / 2.0
            target_rect = QtCore.QRectF(tx, ty, target_w, target_h)
            painter.drawImage(target_rect, img)

        # --- draw human-readable text in a clean white strip ---
        if hr_pos != "none" and text_rect is not None:
            font = QtGui.QFont(hr_family, hr_size)
            painter.setFont(font)
            painter.setPen(QtCore.Qt.black)

            # make sure bars never bleed through under the text
            painter.fillRect(text_rect, QtCore.Qt.white)

            painter.drawText(
                text_rect,
                int(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter),
                data,
            )

    def _paint_image(self, painter: QtGui.QPainter, w: int, h: int) -> None:
        """
        Draws a bitmap/SVG image into the item rect.

        - Uses elem.image_path
        - Honors elem.keep_aspect (if present, defaults True)
        - Always paints on a white background
        """
        path = getattr(self.elem, "image_path", "") or ""
        if not path or not os.path.exists(path):
            # Placeholder: light gray box with X so you know it's missing
            painter.fillRect(QtCore.QRectF(0, 0, w, h), QtCore.Qt.lightGray)
            pen = QtGui.QPen(QtCore.Qt.darkGray)
            painter.setPen(pen)
            painter.drawLine(0, 0, w, h)
            painter.drawLine(0, h, w, 0)
            return

        # Load image (Qt will handle PNG/JPG/SVG via plugins)
        img = QtGui.QImage(path)
        if img.isNull():
            # same placeholder as missing
            painter.fillRect(QtCore.QRectF(0, 0, w, h), QtCore.Qt.lightGray)
            pen = QtGui.QPen(QtCore.Qt.darkGray)
            painter.setPen(pen)
            painter.drawLine(0, 0, w, h)
            painter.drawLine(0, h, w, 0)
            return

        # Optional: flatten alpha onto white so transparent PNGs look right
        if img.hasAlphaChannel():
            flat = QtGui.QImage(img.size(), QtGui.QImage.Format_ARGB32)
            flat.fill(QtCore.Qt.white)
            p = QtGui.QPainter(flat)
            p.drawImage(0, 0, img)
            p.end()
            img = flat

        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)

        # White background in the whole rect
        painter.fillRect(QtCore.QRectF(0, 0, w, h), QtCore.Qt.white)

        keep_aspect = bool(getattr(self.elem, "keep_aspect", True))

        if not keep_aspect or img.width() <= 0 or img.height() <= 0:
            # Simple stretch to fit
            target_rect = QtCore.QRectF(0, 0, w, h)
            painter.drawImage(target_rect, img)
            return

        # Aspect-ratio-preserving fit & center
        src_w = float(img.width())
        src_h = float(img.height())
        src_ratio = src_w / src_h
        dst_ratio = float(w) / float(h) if h > 0 else 1.0

        if dst_ratio > src_ratio:
            # match height
            target_h = float(h)
            target_w = target_h * src_ratio
        else:
            # match width
            target_w = float(w)
            target_h = target_w / src_ratio

        tx = (w - target_w) / 2.0
        ty = (h - target_h) / 2.0
        target_rect = QtCore.QRectF(tx, ty, target_w, target_h)
        painter.drawImage(target_rect, img)

    # ---------- cache & paint ----------
    def _ensure_cache(self):
        r = self.rect()
        w = max(1, int(r.width()))
        h = max(1, int(r.height()))

        # Resolve font size same way as _paint_text so cache matches
        size = getattr(self.elem, "font_point", None)
        if size is None:
            size = getattr(self.elem, "font_size", 12)
        try:
            size = int(size or 12)
        except Exception:
            size = 12


        key = (
            getattr(self.elem, "kind", "text"),
            getattr(self.elem, "text", ""),
            getattr(self.elem, "font_family", "Arial"),
            size,
            bool(getattr(self.elem, "bold", False)),
            bool(getattr(self.elem, "italic", False)),
            getattr(self.elem, "h_align", "left"),
            getattr(self.elem, "v_align", "top"),
            getattr(self.elem, "wrap_mode", "word"),
            bool(getattr(self.elem, "shrink_to_fit", False)),
            int(getattr(self.elem, "max_lines", 0) or 0),
            # barcode-specific
            getattr(self.elem, "bc_type", ""),
            getattr(self.elem, "bc_hr_pos", ""),
            getattr(self.elem, "bc_hr_font_family", ""),
            int(getattr(self.elem, "bc_hr_font_point", 0) or 0),
            # image-specific
            getattr(self.elem, "image_path", ""),
            bool(getattr(self.elem, "keep_aspect", True)),
            w,
            h,
        )

        if key == self._cache_key and self._cache_qimage is not None:
            return

        img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        try:
            kind = getattr(self.elem, "kind", "text")
            if kind == "text":
                self._paint_text(p, w, h)
            elif kind == "barcode":
                self._paint_barcode(p, w, h)
            elif kind == "image":
                self._paint_image(p, w, h)
            else:
                # other kinds (shapes, etc.) could be painted here if needed
                pass
        finally:
            p.end()

        self._cache_qimage = img
        self._cache_key = key

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget=None,
    ) -> None:
        self._ensure_cache()
        r = self.rect()

        if self._cache_qimage is not None:
            img = self._cache_qimage

            # If the world transform is mirrored in X (m11 < 0),
            # then the item would be drawn backwards. Counteract
            # that by mirroring the cached image horizontally.
            tf = painter.worldTransform()
            try:
                if tf.m11() < 0:
                    img = img.mirrored(True, False)
            except Exception:
                # If anything weird happens, just fall back to the original image.
                img = self._cache_qimage

            painter.drawImage(r, img)

        # selection outline
        if self.isSelected():
            pen = QtGui.QPen(QtGui.QColor("#0078d7"))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(r)

            # resize handle
            painter.fillRect(self._handle_rect(), QtGui.QColor("#0078d7"))

    # ---- locking helpers -------------------------------------------------
    @property
    def lock_mode(self) -> str:
        elem = getattr(self, "elem", None)
        if elem is None:
            return "none"

        mode = getattr(elem, "lock_mode", None)
        if mode in ("none", "position", "style", "full"):
            return mode

        # Backward compat: old boolean "locked" means full lock
        if getattr(elem, "locked", False):
            return "full"
        return "none"

    def is_position_locked(self) -> bool:
        return self.lock_mode in ("position", "full")

    def is_style_locked(self) -> bool:
        return self.lock_mode in ("style", "full")

    # ---------- interaction & sync with Element ----------
    def hoverMoveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        if self.is_position_locked():
            self.setCursor(QtCore.Qt.ArrowCursor)
            return super().hoverMoveEvent(event)

        if self._handle_rect().contains(event.pos()):
            self.setCursor(QtCore.Qt.SizeFDiagCursor)
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            # If position is locked, allow selection but block move/resize start
            if self.is_position_locked():
                self._move_start_pos = None
                self._move_start_rect = None
                self._resizing = False
                return super().mousePressEvent(event)

            # Remember starting geometry for undo
            self._move_start_pos = QtCore.QPointF(self.pos())
            self._move_start_rect = QtCore.QRectF(self.rect())

            # Check for resize handle
            if self._handle_rect().contains(event.pos()):
                self._resizing = True
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self.is_position_locked():
            event.accept()
            return

        if self._resizing:
            new_w = max(10, event.pos().x())
            new_h = max(10, event.pos().y())

            # Keep QR Code barcodes perfectly square
            kind = getattr(self.elem, "kind", "text")
            if kind == "barcode":
                bc_type = str(getattr(self.elem, "bc_type", "")).lower()
                if "qr" in bc_type:
                    side = max(new_w, new_h)
                    new_w = new_h = side

            self.setRect(0, 0, new_w, new_h)

            # sync element size
            self.elem.w = float(new_w)
            self.elem.h = float(new_h)

            self._cache_qimage = None
            self._cache_key = None
            self.update()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self.is_position_locked():
            self._resizing = False
            self._move_start_pos = None
            self._move_start_rect = None
            return super().mouseReleaseEvent(event)
        moved_or_resized = False

        if event.button() == QtCore.Qt.LeftButton:
            end_pos = QtCore.QPointF(self.pos())
            end_rect = QtCore.QRectF(self.rect())

            if self._move_start_pos is not None and self._move_start_rect is not None:
                if (end_pos != self._move_start_pos) or (end_rect != self._move_start_rect):
                    moved_or_resized = True

        if self._resizing and event.button() == QtCore.Qt.LeftButton:
            self._resizing = False

        super().mouseReleaseEvent(event)

        # If geometry changed and we have an undo stack, push a command
        if moved_or_resized and self.undo_stack is not None:
            try:
                cmd = MoveResizeCmd(
                    self,
                    self._move_start_pos,
                    self._move_start_rect,
                    QtCore.QPointF(self.pos()),
                    QtCore.QRectF(self.rect()),
                    text="Move/resize item",
                )
                self.undo_stack.push(cmd)
            except Exception:
                # Failsafe: do nothing, at least we don't crash the UI
                pass

        self._move_start_pos = None
        self._move_start_rect = None

    def itemChange(
        self,
        change: QtWidgets.QGraphicsItem.GraphicsItemChange,
        value,
    ):
        """
        Live snapping during drag / keyboard move.

        Snaps to:
        - 0.5 mm grid
        - Page margins (inside edges)
        - Page center X/Y (aligns ITEM CENTER to page center)
        - Column guides (NEW - Patch 6)
        """
        if change == QtWidgets.QGraphicsItem.ItemPositionChange and self.scene():
            if self.is_position_locked():
                return self.pos()

            new_pos: QtCore.QPointF = value
            scene = self.scene()

            orig_x = new_pos.x()
            orig_y = new_pos.y()

            # px/mm factor
            try:
                factor = float(PX_PER_MM) if PX_PER_MM else 1.0
            except Exception:
                factor = 1.0

            SNAP_MM = 0.5
            snap_px = SNAP_MM * factor if factor > 0 else 8.0
            tol_px = snap_px * 3.0  # forgiving

            def snap_val(v: float) -> float:
                if snap_px <= 0:
                    return v
                return round(v / snap_px) * snap_px

            # base grid snap
            grid_x = snap_val(orig_x)
            grid_y = snap_val(orig_y)

            scene_rect = scene.sceneRect()
            paper_w = scene_rect.width()
            paper_h = scene_rect.height()

            # Margins on scene, in mm
            margins_mm = getattr(scene, "margins_mm", (0.0, 0.0, 0.0, 0.0))
            try:
                ml, mt, mr, mb = margins_mm
            except Exception:
                ml = mt = mr = mb = 0.0

            left_margin_x = ml * factor
            right_margin_x = paper_w - (mr * factor)
            top_margin_y = mt * factor
            bottom_margin_y = paper_h - (mb * factor)
            center_x = paper_w / 2.0
            center_y = paper_h / 2.0

            # Our own bounding rect (for right/bottom + center alignment)
            try:
                br = self.boundingRect()
                bw = br.width()
                bh = br.height()
            except Exception:
                bw = bh = 0.0

            # ---------- X candidates ----------
            x_candidates = [grid_x]

            # Left margin (align left edge)
            if abs(orig_x - left_margin_x) < tol_px:
                x_candidates.append(left_margin_x)

            # Page center (align ITEM CENTER to page center)
            if bw > 0:
                item_center_x = orig_x + (bw / 2.0)
                if abs(item_center_x - center_x) < tol_px:
                    x_candidates.append(center_x - (bw / 2.0))

            # Right margin (align right edge to inside margin)
            if bw > 0:
                right_target = right_margin_x - bw
                if abs(orig_x - right_target) < tol_px:
                    x_candidates.append(right_target)

            # ========== NEW: Column guide snapping (Patch 6) ==========
            column_guide_positions = getattr(scene, 'column_guide_positions', [])
            if column_guide_positions and bw > 0:
                for guide_x in column_guide_positions:
                    # Snap left edge to guide
                    if abs(orig_x - guide_x) < tol_px:
                        x_candidates.append(guide_x)
                    
                    # Snap right edge to guide
                    right_edge = orig_x + bw
                    if abs(right_edge - guide_x) < tol_px:
                        x_candidates.append(guide_x - bw)
                    
                    # Snap center to guide
                    item_center_x = orig_x + (bw / 2.0)
                    if abs(item_center_x - guide_x) < tol_px:
                        x_candidates.append(guide_x - (bw / 2.0))
            # ========== END NEW ==========

            x = min(x_candidates, key=lambda c: abs(c - orig_x))

            # ---------- Y candidates ----------
            y_candidates = [grid_y]

            # Top margin
            if abs(orig_y - top_margin_y) < tol_px:
                y_candidates.append(top_margin_y)

            # Page center Y (align ITEM CENTER to page center)
            if bh > 0:
                item_center_y = orig_y + (bh / 2.0)
                if abs(item_center_y - center_y) < tol_px:
                    y_candidates.append(center_y - (bh / 2.0))

            # Bottom margin
            if bh > 0:
                bottom_target = bottom_margin_y - bh
                if abs(orig_y - bottom_target) < tol_px:
                    y_candidates.append(bottom_target)

            y = min(y_candidates, key=lambda c: abs(c - orig_y))

            snapped = QtCore.QPointF(x, y)

            # Keep model in sync
            if hasattr(self, "elem"):
                try:
                    self.elem.x = snapped.x()
                    self.elem.y = snapped.y()
                except Exception:
                    pass

            return snapped

        return super().itemChange(change, value)


class GLineItem(ContextMenuMixin, QtWidgets.QGraphicsLineItem):
    """
    Movable + resizable line with:
    - Handles on both endpoints
    - Undo/redo for move + resize
    - Shift+drag snapping to "nice" angles (0°, 45°, 90°, etc.)
    """

    HANDLE_RADIUS = 6.0

    def __init__(self, p1: QtCore.QPointF, p2: QtCore.QPointF, parent=None):
        super().__init__(QtCore.QLineF(p1, p2), parent)

        self.setFlags(
            QtWidgets.QGraphicsItem.ItemIsSelectable
            | QtWidgets.QGraphicsItem.ItemIsMovable
            | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)

        # undo stack (set by MainWindow)
        self.undo_stack = None

        # move tracking
        self._move_start_pos: QtCore.QPointF | None = None

        # resize tracking
        self._resizing: bool = False
        self._resize_which: str | None = None  # "p1" or "p2"
        self._resize_old_line: QtCore.QLineF | None = None

        # style
        pen = QtGui.QPen(QtGui.QColor("#000000"))
        pen.setWidthF(1.3)
        self.setPen(pen)

    # ---------- geometry helpers ----------

    def _handle_centers(self) -> tuple[QtCore.QPointF, QtCore.QPointF]:
        """
        Returns (p1, p2) in item coordinates.
        """
        ln = self.line()
        return (ln.p1(), ln.p2())

    def _hit_handle(self, pos: QtCore.QPointF) -> str | None:
        """
        Returns "p1", "p2", or None depending on which endpoint is under the cursor.
        pos is in item coordinates.
        """
        p1, p2 = self._handle_centers()
        r = self.HANDLE_RADIUS * 1.5

        if QtCore.QLineF(pos, p1).length() <= r:
            return "p1"
        if QtCore.QLineF(pos, p2).length() <= r:
            return "p2"
        return None

    # ---------- bounding rect ----------

    def boundingRect(self) -> QtCore.QRectF:
        """
        Expand the bounding rect a bit to include the endpoint handles.
        """
        r = super().boundingRect()
        pad = self.HANDLE_RADIUS + 2.0
        return QtCore.QRectF(
            r.x() - pad,
            r.y() - pad,
            r.width() + pad * 2.0,
            r.height() + pad * 2.0,
        )

    # ---------- painting ----------

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget=None,
    ) -> None:
        # draw the line normally
        super().paint(painter, option, widget)

        # draw handles when selected
        if self.isSelected():
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#0078d7"))

            p1, p2 = self._handle_centers()
            r = self.HANDLE_RADIUS

            for pt in (p1, p2):
                rect = QtCore.QRectF(pt.x() - r, pt.y() - r, r * 2.0, r * 2.0)
                painter.drawEllipse(rect)

    # ---------- cursor feedback ----------

    def hoverMoveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        handle = self._hit_handle(event.pos())
        if handle is not None:
            self.setCursor(QtCore.Qt.SizeAllCursor)  # resize handle
        else:
            self.setCursor(QtCore.Qt.SizeAllCursor)  # move
        super().hoverMoveEvent(event)

    # ---------- mouse + undo ----------

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            handle = self._hit_handle(event.pos())
            if handle is not None:
                # start resize
                self._resizing = True
                self._resize_which = handle
                self._resize_old_line = QtCore.QLineF(self.line())
                event.accept()
                return
            else:
                # start move
                self._move_start_pos = QtCore.QPointF(self.pos())

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._resizing:
            ln = QtCore.QLineF(self.line())

            # anchor = the opposite endpoint
            if self._resize_which == "p1":
                anchor = ln.p2()
            else:
                anchor = ln.p1()

            raw = event.pos()

            # Shift = snap to nice angles
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                dx = raw.x() - anchor.x()
                dy = raw.y() - anchor.y()
                length = math.hypot(dx, dy)
                if length < 1e-3:
                    # too small, don't change
                    new_pt = raw
                else:
                    angle = math.atan2(dy, dx)

                    snaps = [i * (math.pi / 8.0) for i in range(-8, 9)]

                    best = min(snaps, key=lambda a: abs(a - angle))
                    dx = length * math.cos(best)
                    dy = length * math.sin(best)
                    new_pt = QtCore.QPointF(anchor.x() + dx, anchor.y() + dy)
            else:
                new_pt = raw

            if self._resize_which == "p1":
                ln.setP1(new_pt)
            else:
                ln.setP2(new_pt)

            self.setLine(ln)
            self.update()
            event.accept()
            return

        # not resizing → normal move
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        moved = False
        resized = False
        new_line: QtCore.QLineF | None = None

        if event.button() == QtCore.Qt.LeftButton:
            if self._resizing:
                self._resizing = False
                if self._resize_old_line is not None:
                    new_line = QtCore.QLineF(self.line())
                    if new_line != self._resize_old_line:
                        resized = True
            elif self._move_start_pos is not None:
                end_pos = QtCore.QPointF(self.pos())
                if end_pos != self._move_start_pos:
                    moved = True

        super().mouseReleaseEvent(event)

        # Undo for resize
        if (
            resized
            and self.undo_stack is not None
            and self._resize_old_line is not None
            and new_line is not None
        ):
            try:
                cmd = ResizeLineCmd(
                    self,
                    self._resize_old_line,
                    new_line,
                    text="Resize line",
                )
                self.undo_stack.push(cmd)
            except Exception:
                pass

        # Undo for move
        if moved and self.undo_stack is not None and self._move_start_pos is not None:
            try:
                cmd = MoveLineCmd(
                    self,
                    self._move_start_pos,
                    QtCore.QPointF(self.pos()),
                    text="Move line",
                )
                self.undo_stack.push(cmd)
            except Exception:
                pass

        self._move_start_pos = None
        self._resize_old_line = None
        self._resize_which = None

class GArrowItem(GLineItem):
    """
    Arrow shape based on GLineItem:
      - same movement / resize behavior
      - draws an arrow head on one end (start or end)
      - arrow_length_px: along the line
      - arrow_width_px: total width (tip to widest part)
      - arrow_at_start: if True, head at p1; else at p2
    """

    def __init__(
        self,
        p1: QtCore.QPointF | None = None,
        p2: QtCore.QPointF | None = None,
        parent=None,
    ):
        if p1 is None:
            p1 = QtCore.QPointF(20, 20)
        if p2 is None:
            p2 = QtCore.QPointF(80, 20)

        super().__init__(p1, p2, parent)

        # Head geometry in *pixels*
        self.arrow_length_px: float = 10.0
        self.arrow_width_px: float = 6.0
        # Which end has the head? False = end (p2), True = start (p1)
        self.arrow_at_start: bool = False

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget=None,
    ) -> None:
        # Base line + handles from GLineItem
        super().paint(painter, option, widget)

        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        pen = self.pen()
        painter.setPen(pen)
        painter.setBrush(pen.color())

        line = self.line()
        p1 = line.p1()
        p2 = line.p2()

        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        if dx == 0 and dy == 0:
            return

        # Direction angle from p1 -> p2 in Qt coords (y downward)
        angle = math.atan2(-dy, dx)
        vx = math.cos(angle)
        vy = -math.sin(angle)

        length = max(2.0, float(self.arrow_length_px))
        width = max(2.0, float(self.arrow_width_px))
        half_w = width / 2.0

        # Which point is the tip?
        if self.arrow_at_start:
            tip = p1
            # base goes "forward" from p1 towards p2
            base_cx = tip.x() + length * vx
            base_cy = tip.y() + length * vy
        else:
            tip = p2
            # base goes "backwards" from p2 towards p1
            base_cx = tip.x() - length * vx
            base_cy = tip.y() - length * vy

        # Perpendicular vector for width
        # (vx, vy) is along the line; (-vy, vx) is perpendicular
        px_v = -vy
        py_v = vx

        left_x = base_cx + half_w * px_v
        left_y = base_cy + half_w * py_v
        right_x = base_cx - half_w * px_v
        right_y = base_cy - half_w * py_v

        p_left = QtCore.QPointF(left_x, left_y)
        p_right = QtCore.QPointF(right_x, right_y)

        poly = QtGui.QPolygonF([tip, p_left, p_right])
        painter.drawPolygon(poly)


class BaseShapeItem(ContextMenuMixin, QtWidgets.QGraphicsRectItem):
    """
    Base class for simple shapes (rect, ellipse, star) with:
    - move
    - resize via bottom-right handle
    - undo/redo via MoveResizeCmd
    """

    HANDLE_SZ = 10

    def __init__(self, rect: QtCore.QRectF):
        super().__init__(rect)

        self.setFlags(
            QtWidgets.QGraphicsItem.ItemIsMovable
            | QtWidgets.QGraphicsItem.ItemIsSelectable
            | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges
            | QtWidgets.QGraphicsItem.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)

        # hook to QUndoStack (set from MainWindow)
        self.undo_stack = None

        self._resizing = False
        self._move_start_pos: QtCore.QPointF | None = None
        self._move_start_rect: QtCore.QRectF | None = None

        # default style
        self.setPen(QtGui.QPen(QtGui.QColor("#000000")))
        self.setBrush(QtCore.Qt.NoBrush)

    # --- handle geometry ---

    def _handle_rect(self) -> QtCore.QRectF:
        r = self.rect()
        return QtCore.QRectF(
            r.right() - self.HANDLE_SZ,
            r.bottom() - self.HANDLE_SZ,
            self.HANDLE_SZ,
            self.HANDLE_SZ,
        )

    # --- paint ---

    def _paint_shape(self, painter: QtGui.QPainter) -> None:
        """
        Default: simple rectangle. Subclasses override.
        """
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRect(self.rect())

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget=None,
    ) -> None:
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        # draw actual shape
        self._paint_shape(painter)

        # selection outline + resize handle
        if self.isSelected():
            sel_pen = QtGui.QPen(QtGui.QColor("#0078d7"))
            sel_pen.setWidth(1)
            painter.setPen(sel_pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(self.rect())

            painter.fillRect(self._handle_rect(), QtGui.QColor("#0078d7"))

    # --- interaction & undo ---

    def hoverMoveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        if self._handle_rect().contains(event.pos()):
            self.setCursor(QtCore.Qt.SizeFDiagCursor)
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            # remember starting geometry for undo
            self._move_start_pos = QtCore.QPointF(self.pos())
            self._move_start_rect = QtCore.QRectF(self.rect())

            # resize handle?
            if self._handle_rect().contains(event.pos()):
                self._resizing = True
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._resizing:
            r = self.rect()
            new_w = max(5.0, event.pos().x())
            new_h = max(5.0, event.pos().y())
            self.setRect(0.0, 0.0, new_w, new_h)
            self.update()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        moved_or_resized = False

        if event.button() == QtCore.Qt.LeftButton: # pyright: ignore[reportAttributeAccessIssue]
            end_pos = QtCore.QPointF(self.pos())
            end_rect = QtCore.QRectF(self.rect())

            if self._move_start_pos is not None and self._move_start_rect is not None:
                if (end_pos != self._move_start_pos) or (end_rect != self._move_start_rect):
                    moved_or_resized = True

        if self._resizing and event.button() == QtCore.Qt.LeftButton: # type: ignore
            self._resizing = False

        super().mouseReleaseEvent(event)

        if moved_or_resized and self.undo_stack is not None:
            try:
                cmd = MoveResizeCmd(
                    self,
                    self._move_start_pos,
                    self._move_start_rect,
                    QtCore.QPointF(self.pos()),
                    QtCore.QRectF(self.rect()),
                    text="Move/resize shape",
                )
                self.undo_stack.push(cmd)
            except Exception:
                pass

        self._move_start_pos = None
        self._move_start_rect = None


class GRectItem(ContextMenuMixin, QtWidgets.QGraphicsRectItem):
    """
    Rectangle shape with:
      - resize handle (bottom-right)
      - stroke from QPen
      - rounded corners via corner_radius_px
      - pill_mode -> radius = height / 2
    """

    HANDLE_SZ = 10

    def __init__(self, rect: QtCore.QRectF | None = None, parent=None):
        if rect is None:
            rect = QtCore.QRectF(0, 0, 60, 30)
        super().__init__(rect, parent)

        self.setFlags(
            QtWidgets.QGraphicsItem.ItemIsMovable
            | QtWidgets.QGraphicsItem.ItemIsSelectable
            | QtWidgets.QGraphicsItem.ItemIsFocusable
            | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        # extra style properties
        self.corner_radius_px: float = 0.0
        self.pill_mode: bool = False

        self._resizing = False

        pen = QtGui.QPen(QtGui.QColor("#000000"))
        pen.setWidthF(1.0)
        self.setPen(pen)
        self.setBrush(QtCore.Qt.NoBrush)

    # ---------- resize handle helpers ----------

    def _handle_rect(self) -> QtCore.QRectF:
        r = self.rect()
        return QtCore.QRectF(
            r.right() - self.HANDLE_SZ,
            r.bottom() - self.HANDLE_SZ,
            self.HANDLE_SZ,
            self.HANDLE_SZ,
        )

    def _effective_radius(self) -> float:
        r = self.rect()
        w = r.width()
        h = r.height()
        if w <= 0 or h <= 0:
            return 0.0
        if self.pill_mode:
            return h / 2.0
        # clamp to half of min dimension
        return max(0.0, min(self.corner_radius_px, min(w, h) / 2.0))

    # ---------- painting ----------

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget=None,
    ) -> None:
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        r = self.rect()

        radius = self._effective_radius()

        path = QtGui.QPainterPath()
        if radius > 0.0:
            path.addRoundedRect(r, radius, radius)
        else:
            path.addRect(r)

        # main shape
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawPath(path)

        # selection overlay + resize handle
        if self.isSelected():
            sel_pen = QtGui.QPen(QtGui.QColor("#0078d7"))
            sel_pen.setStyle(QtCore.Qt.DashLine)
            sel_pen.setWidth(1)
            painter.setPen(sel_pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(r)

            painter.fillRect(self._handle_rect(), QtGui.QColor("#0078d7"))

    # ---------- interaction (resize) ----------

    def hoverMoveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        if self._handle_rect().contains(event.pos()):
            self.setCursor(QtCore.Qt.SizeFDiagCursor)
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if (
            event.button() == QtCore.Qt.LeftButton
            and self._handle_rect().contains(event.pos())
        ):
            self._resizing = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._resizing:
            r = self.rect()
            new_w = max(10.0, event.pos().x())
            new_h = max(10.0, event.pos().y())
            self.setRect(0, 0, new_w, new_h)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._resizing and event.button() == QtCore.Qt.LeftButton:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)



class GEllipseItem(BaseShapeItem):
    """
    Simple circle/ellipse outline.
    """

    def __init__(self, rect: QtCore.QRectF | None = None):
        if rect is None:
            rect = QtCore.QRectF(0.0, 0.0, 50.0, 50.0)
        super().__init__(rect)

    def _paint_shape(self, painter: QtGui.QPainter) -> None:
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawEllipse(self.rect())


class GStarItem(ContextMenuMixin, QtWidgets.QGraphicsRectItem):
    """
    Star shape item with:
      - star_points (min 3) controllable from PropertiesPanel
      - resize handle at bottom-right (like GItem)
      - movable/selectable, shows selection rect
    """

    HANDLE_SZ = 10

    def __init__(
        self,
        rect: QtCore.QRectF | None = None,
        parent=None,
        points: int = 5,
    ):
        if rect is None:
            rect = QtCore.QRectF(0, 0, 40, 40)
        super().__init__(rect, parent)

        self.setFlags(
            QtWidgets.QGraphicsItem.ItemIsMovable
            | QtWidgets.QGraphicsItem.ItemIsSelectable
            | QtWidgets.QGraphicsItem.ItemIsFocusable
            | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        self.star_points = max(3, int(points))
        self._resizing = False

        pen = QtGui.QPen(QtGui.QColor("#000000"))
        pen.setWidthF(1.3)
        self.setPen(pen)
        self.setBrush(QtCore.Qt.NoBrush)

    # ---------- resize handle helpers ----------

    def _handle_rect(self) -> QtCore.QRectF:
        r = self.rect()
        return QtCore.QRectF(
            r.right() - self.HANDLE_SZ,
            r.bottom() - self.HANDLE_SZ,
            self.HANDLE_SZ,
            self.HANDLE_SZ,
        )

    # ---------- star path ----------

    def _build_star_path(self) -> QtGui.QPainterPath:
        """
        Build a star inside self.rect(), honoring self.star_points.
        """
        rect = self.rect()

        cx = rect.center().x()
        cy = rect.center().y()

        outer_r = min(rect.width(), rect.height()) / 2.0
        inner_r = outer_r * 0.5

        n = max(3, int(getattr(self, "star_points", 5) or 5))

        path = QtGui.QPainterPath()

        start_angle = -math.pi / 2.0
        angle_step = math.pi / n  # 2n points around circle (outer/inner alternating)

        for i in range(2 * n + 1):
            r = outer_r if (i % 2 == 0) else inner_r
            angle = start_angle + i * angle_step
            x = cx + r * math.cos(angle)
            y = cy + r * math.sin(angle)
            pt = QtCore.QPointF(x, y)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)

        path.closeSubpath()
        return path

    # ---------- painting ----------

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget=None,
    ) -> None:
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        # star
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        path = self._build_star_path()
        painter.drawPath(path)

        # selection overlay + resize handle
        if self.isSelected():
            r = self.rect()

            sel_pen = QtGui.QPen(QtGui.QColor("#0078d7"))
            sel_pen.setStyle(QtCore.Qt.DashLine)
            sel_pen.setWidth(1)
            painter.setPen(sel_pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(r)

            # resize handle square
            painter.fillRect(self._handle_rect(), QtGui.QColor("#0078d7"))

    # ---------- interaction (resize + move) ----------

    def hoverMoveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        if self._handle_rect().contains(event.pos()):
            self.setCursor(QtCore.Qt.SizeFDiagCursor)
        else:
            self.setCursor(QtCore.Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if (
            event.button() == QtCore.Qt.LeftButton
            and self._handle_rect().contains(event.pos())
        ):
            self._resizing = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._resizing:
            r = self.rect()
            # keep top-left anchored; grow width/height
            new_w = max(10.0, event.pos().x())
            new_h = max(10.0, event.pos().y())
            self.setRect(0, 0, new_w, new_h)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if self._resizing and event.button() == QtCore.Qt.LeftButton:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

class GDiamondItem(BaseShapeItem):
    """
    Diamond shape: drawn inside its rect as a rotated square (diamond).
    Uses BaseShapeItem for:
      - move
      - resize via bottom-right handle
      - undo/redo via MoveResizeCmd
      - context menu via ContextMenuMixin
    """

    def __init__(self, rect: QtCore.QRectF | None = None):
        if rect is None:
            rect = QtCore.QRectF(0.0, 0.0, 40.0, 40.0)
        super().__init__(rect)

        pen = QtGui.QPen(QtGui.QColor("#000000"))
        pen.setWidthF(1.3)
        self.setPen(pen)
        self.setBrush(QtCore.Qt.NoBrush)

    def _paint_shape(self, painter: QtGui.QPainter) -> None:
        r = self.rect()
        cx = r.center().x()
        cy = r.center().y()

        # Four points: left, top, right, bottom → diamond
        pts = [
            QtCore.QPointF(r.left(),  cy),
            QtCore.QPointF(cx,        r.top()),
            QtCore.QPointF(r.right(), cy),
            QtCore.QPointF(cx,        r.bottom()),
        ]
        poly = QtGui.QPolygonF(pts)

        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawPolygon(poly)



class GuideGridItem(ContextMenuMixin, QtWidgets.QGraphicsItem):
    def boundingRect(self) -> QtCore.QRectF:
        return QtCore.QRectF()

    def paint(self, p: QtGui.QPainter, opt, widget=None):
        pass


class GuideLineItem(ContextMenuMixin, QtWidgets.QGraphicsLineItem):
    pass
