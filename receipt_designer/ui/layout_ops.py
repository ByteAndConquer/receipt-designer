# receipt_designer/ui/layout_ops.py
"""
Layout operations: align, distribute, group, z-order, lock, nudge,
duplicate, baseline snap, delete, hide/show.

All public functions accept *mw* (the MainWindow instance);
this module must NOT import main_window_impl to avoid circular imports.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtWidgets

from ..core.models import Element
from ..core.commands import DeleteItemCmd, GroupItemsCmd, UngroupItemsCmd
from .items import (
    GItem,
    GLineItem,
    GRectItem,
    GEllipseItem,
    GStarItem,
    GDiamondItem,
)
from .common import px_per_mm_factor, unpack_margins_mm

if TYPE_CHECKING:
    from .host_protocols import LayoutHost


# ---------------------------------------------------------------------------
# Nudge / duplicate
# ---------------------------------------------------------------------------

def nudge_selected(mw: LayoutHost, dx: float, dy: float) -> None:
    items = mw.scene.selectedItems()
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


def duplicate_selected_items(mw: LayoutHost) -> None:
    """Duplicate selected items with remembered offset."""
    items = mw.scene.selectedItems()
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

            new_elem.x = float(getattr(it.elem, "x", 0.0)) + mw._last_duplicate_offset.x()
            new_elem.y = float(getattr(it.elem, "y", 0.0)) + mw._last_duplicate_offset.y()

            new_item = GItem(new_elem)
            new_item.undo_stack = mw.undo_stack
            new_item._main_window = mw
            mw.scene.addItem(new_item)
            new_item.setPos(new_elem.x, new_elem.y)
            new_items.append(new_item)

    if new_items:
        mw.scene.clearSelection()
        for ni in new_items:
            ni.setSelected(True)
        mw._refresh_layers_safe()

        mw.statusBar().showMessage(
            f"Duplicated {len(new_items)} item(s) at offset "
            f"({mw._last_duplicate_offset.x():.0f}, {mw._last_duplicate_offset.y():.0f}) px",
            3000
        )


# ---------------------------------------------------------------------------
# Align / distribute
# ---------------------------------------------------------------------------

def align_selected(mw: LayoutHost, mode: str) -> None:
    """
    Align selected items to either the page or the printable area (margins).

    Locked items (data(0) == 'locked') are not moved.
    """
    items = [
        it
        for it in mw.scene.selectedItems()
        if isinstance(it, (GItem, GRectItem, GEllipseItem, GStarItem, GLineItem, GDiamondItem))
        and it.data(0) != "locked"
    ]
    if not items:
        return

    scene_rect = mw.scene.sceneRect()
    page_w = scene_rect.width()
    page_h = scene_rect.height()

    ml, mt, mr, mb = unpack_margins_mm(mw.scene)
    factor = px_per_mm_factor()

    margin_left_x = ml * factor
    margin_right_x = page_w - (mr * factor)
    margin_top_y = mt * factor
    margin_bottom_y = page_h - (mb * factor)

    use_margins = getattr(mw, "act_align_use_margins", None)
    use_margins = bool(use_margins and mw.act_align_use_margins.isChecked())

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

    area_hcenter = (area_left_x + area_right_x) / 2.0
    area_vcenter = (area_top_y + area_bottom_y) / 2.0

    for it in items:
        r = it.sceneBoundingRect()
        dx = 0.0
        dy = 0.0

        if mode == "left":
            dx = area_left_x - r.left()
        elif mode == "hcenter":
            dx = area_hcenter - r.center().x()
        elif mode == "right":
            dx = area_right_x - r.right()

        if mode == "top":
            dy = area_top_y - r.top()
        elif mode == "vcenter":
            dy = area_vcenter - r.center().y()
        elif mode == "bottom":
            dy = area_bottom_y - r.bottom()

        if dx == 0.0 and dy == 0.0:
            continue

        it.moveBy(dx, dy)

        if hasattr(it, "elem"):
            try:
                it.elem.x = float(it.pos().x())
                it.elem.y = float(it.pos().y())
            except Exception:
                pass

    mw._refresh_layers_safe()


def distribute_selected(mw: LayoutHost, axis: str) -> None:
    """
    Distribute selected items evenly along axis:
    axis == 'h' -> horizontal (X centers)
    axis == 'v' -> vertical (Y centers)

    Locked items (data(0) == 'locked') are not moved.
    """
    items = [
        it
        for it in mw.scene.selectedItems()
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
        data.sort(key=lambda d: d[3])
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
        data.sort(key=lambda d: d[4])
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


# ---------------------------------------------------------------------------
# Group / ungroup
# ---------------------------------------------------------------------------

def group_selected(mw: LayoutHost) -> None:
    """Group selected items into a QGraphicsItemGroup (undoable)."""
    sel = mw.scene.selectedItems()
    items = [it for it in sel if not isinstance(it, QtWidgets.QGraphicsItemGroup)]
    if len(items) < 2:
        return

    cmd = GroupItemsCmd(mw.scene, items, text="Group items")
    mw.undo_stack.push(cmd)
    mw._refresh_layers_safe()


def ungroup_selected(mw: LayoutHost) -> None:
    """Ungroup any selected QGraphicsItemGroup (undoable)."""
    groups = [
        it
        for it in mw.scene.selectedItems()
        if isinstance(it, QtWidgets.QGraphicsItemGroup)
    ]
    if not groups:
        return

    cmd = UngroupItemsCmd(mw.scene, groups, text="Ungroup items")
    mw.undo_stack.push(cmd)
    mw._refresh_layers_safe()


# ---------------------------------------------------------------------------
# Z-order
# ---------------------------------------------------------------------------

def change_z_order(mw: LayoutHost, mode: str) -> None:
    """
    mode:
        'front' -> bring to front
        'back'  -> send to back
        'up'    -> bring forward
        'down'  -> send backward
    """
    sel = mw.scene.selectedItems()
    if not sel:
        return

    all_items = mw.scene.items()
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

    mw._refresh_layers_safe()


# ---------------------------------------------------------------------------
# Lock / unlock
# ---------------------------------------------------------------------------

def lock_selected(mw: LayoutHost) -> None:
    """Lock selected items: prevent moving/resizing, but keep selectable."""
    for it in mw.scene.selectedItems():
        it.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, False)
        it.setData(0, "locked")


def unlock_selected(mw: LayoutHost) -> None:
    """Unlock selected items (re-allow movement)."""
    for it in mw.scene.selectedItems():
        if it.data(0) == "locked":
            it.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, True)
            it.setData(0, None)


# ---------------------------------------------------------------------------
# Baseline snap
# ---------------------------------------------------------------------------

def apply_baseline_to_selected(mw: LayoutHost) -> None:
    """
    Snap selected items' Y to a baseline grid.

    Uses mw.sb_baseline_mm, and aligns relative to:
    - top margin if "align to margins" is on
    - page top if it's off

    Locked items (data(0) == 'locked') are not moved.
    """
    items = [
        it
        for it in mw.scene.selectedItems()
        if isinstance(it, GItem) and it.data(0) != "locked"
    ]
    if not items:
        return

    step_mm = float(mw.sb_baseline_mm.value())
    if step_mm <= 0:
        return

    factor = px_per_mm_factor()
    step_px = step_mm * factor

    ml, mt, mr, mb = unpack_margins_mm(mw.scene)

    use_margins = getattr(mw, "act_align_use_margins", None)
    use_margins = bool(use_margins and mw.act_align_use_margins.isChecked())

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


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_selected_items(mw: LayoutHost) -> None:
    """Delete selected items via DeleteItemCmd so it's undoable."""
    sel = mw.scene.selectedItems()
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

    cmd = DeleteItemCmd(mw.scene, items, text="Delete item(s)")
    mw.undo_stack.push(cmd)
    mw._refresh_layers_safe()


# ---------------------------------------------------------------------------
# Hide / show
# ---------------------------------------------------------------------------

def hide_selected(mw: LayoutHost) -> None:
    """Hide selected items."""
    for it in mw.scene.selectedItems():
        it.setVisible(False)
        it.setData(1, "hidden_by_tool")


def show_all_hidden(mw: LayoutHost) -> None:
    """Show all items previously hidden by hide_selected."""
    for it in mw.scene.items():
        if it.data(1) == "hidden_by_tool":
            it.setVisible(True)
