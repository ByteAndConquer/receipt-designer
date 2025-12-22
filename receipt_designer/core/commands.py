from __future__ import annotations

from typing import Iterable, List, Optional

from PySide6 import QtCore, QtWidgets, QtGui


class AddItemCmd(QtGui.QUndoCommand):
    """
    Add a single QGraphicsItem to a scene.

    Intended for things like GItem, GLineItem, etc.
    """

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        item: QtWidgets.QGraphicsItem,
        text: str = "Add item",
    ):
        super().__init__(text)
        self.scene = scene
        self.item = item
        # Remember z / pos if already set
        self._pos = QtCore.QPointF(item.pos())
        self._z = float(item.zValue())

    def redo(self) -> None:
        if self.item.scene() is not self.scene:
            self.scene.addItem(self.item)
        self.item.setPos(self._pos)
        self.item.setZValue(self._z)
        self.item.setSelected(True)

    def undo(self) -> None:
        if self.item.scene() is self.scene:
            self.scene.removeItem(self.item)


class DeleteItemCmd(QtGui.QUndoCommand):
    """
    Delete one or more items from a QGraphicsScene.

    Stores their positions and z-values so they can be restored.
    """

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        items: Iterable[QtWidgets.QGraphicsItem],
        text: str = "Delete item(s)",
    ):
        super().__init__(text)
        self.scene = scene

        # Snapshot items and their state
        self._entries: List[tuple[QtWidgets.QGraphicsItem, QtCore.QPointF, float]] = []
        for it in items:
            self._entries.append(
                (it, QtCore.QPointF(it.pos()), float(it.zValue()))
            )

    def redo(self) -> None:
        for it, _, _ in self._entries:
            if it.scene() is self.scene:
                self.scene.removeItem(it)

    def undo(self) -> None:
        for it, pos, z in self._entries:
            if it.scene() is not self.scene:
                self.scene.addItem(it)
            it.setPos(pos)
            it.setZValue(z)
            it.setSelected(True)


class MoveResizeCmd(QtGui.QUndoCommand):
    """
    Move and/or resize a QGraphicsRectItem (e.g. GItem).

    Tracks:
    - old_pos, old_rect
    - new_pos, new_rect

    Keeps elem.x/y/w/h in sync if the item has an 'elem' attribute.
    """

    def __init__(
        self,
        item: QtWidgets.QGraphicsRectItem,
        old_pos: QtCore.QPointF,
        old_rect: QtCore.QRectF,
        new_pos: QtCore.QPointF,
        new_rect: QtCore.QRectF,
        text: str = "Move/resize item",
    ):
        super().__init__(text)
        self.item = item
        self.old_pos = QtCore.QPointF(old_pos)
        self.old_rect = QtCore.QRectF(old_rect)
        self.new_pos = QtCore.QPointF(new_pos)
        self.new_rect = QtCore.QRectF(new_rect)

    def _apply(self, pos: QtCore.QPointF, rect: QtCore.QRectF) -> None:
        # Set geometry on the graphics item
        self.item.setRect(rect)
        self.item.setPos(pos)

        # Sync back to elem if present
        elem = getattr(self.item, "elem", None)
        if elem is not None:
            try:
                elem.x = float(pos.x())
                elem.y = float(pos.y())
                elem.w = float(rect.width())
                elem.h = float(rect.height())
            except Exception:
                pass

        # Bust any caches the item might have
        if hasattr(self.item, "_cache_qimage"):
            self.item._cache_qimage = None
        if hasattr(self.item, "_cache_key"):
            self.item._cache_key = None

        self.item.update()

    def redo(self) -> None:
        self._apply(self.new_pos, self.new_rect)

    def undo(self) -> None:
        self._apply(self.old_pos, self.old_rect)

class MoveLineCmd(QtGui.QUndoCommand):
    """
    Move a QGraphicsItem (e.g. GLineItem) that is position-based only
    (we don't change its internal line geometry, just its pos()).
    """

    def __init__(
        self,
        item: QtWidgets.QGraphicsItem,
        old_pos: QtCore.QPointF,
        new_pos: QtCore.QPointF,
        text: str = "Move line",
    ):
        super().__init__(text)
        self.item = item
        self.old_pos = QtCore.QPointF(old_pos)
        self.new_pos = QtCore.QPointF(new_pos)

    def _apply(self, pos: QtCore.QPointF) -> None:
        self.item.setPos(pos)

    def redo(self) -> None:
        self._apply(self.new_pos)

    def undo(self) -> None:
        self._apply(self.old_pos)

class ResizeLineCmd(QtGui.QUndoCommand):
    """
    Resize a QGraphicsLineItem by changing its QLineF geometry.
    """

    def __init__(
        self,
        item: QtWidgets.QGraphicsLineItem,
        old_line: QtCore.QLineF,
        new_line: QtCore.QLineF,
        text: str = "Resize line",
    ):
        super().__init__(text)
        self.item = item
        self.old_line = QtCore.QLineF(old_line)
        self.new_line = QtCore.QLineF(new_line)

    def _apply(self, line: QtCore.QLineF) -> None:
        self.item.setLine(line)

    def redo(self) -> None:
        self._apply(self.new_line)

    def undo(self) -> None:
        self._apply(self.old_line)


class PropertyChangeCmd(QtGui.QUndoCommand):
    """
    Generic property change on an element-like object.

    elem:     object to mutate
    prop:     attribute name
    old/new:  values
    item:     optional QGraphicsItem to refresh after change
    """

    def __init__(
        self,
        elem: object,
        prop: str,
        old_value,
        new_value,
        text: str = "Change property",
        item: Optional[QtWidgets.QGraphicsItem] = None,
    ):
        super().__init__(text)
        self.elem = elem
        self.prop = prop
        self.old_value = old_value
        self.new_value = new_value
        self.item = item

    def _apply(self, value) -> None:
        setattr(self.elem, self.prop, value)

        if self.item is not None:
            # bust caches if present
            if hasattr(self.item, "_cache_qimage"):
                self.item._cache_qimage = None
            if hasattr(self.item, "_cache_key"):
                self.item._cache_key = None
            self.item.update()

    def redo(self) -> None:
        self._apply(self.new_value)

    def undo(self) -> None:
        self._apply(self.old_value)

class GroupItemsCmd(QtGui.QUndoCommand):
    """
    Group a set of items into a QGraphicsItemGroup.

    Undo: ungroup them again.
    Redo: regroup them.
    """

    def __init__(self, scene: QtWidgets.QGraphicsScene, items, text: str = "Group items"):
        super().__init__(text)
        self.scene = scene
        # Only keep concrete QGraphicsItems
        self.items = [it for it in items if isinstance(it, QtWidgets.QGraphicsItem)]
        self.group: QtWidgets.QGraphicsItemGroup | None = None

    def _make_group(self):
        if not self.items or self.scene is None:
            return

        self.group = self.scene.createItemGroup(self.items)
        self.group.setFlags(
            QtWidgets.QGraphicsItem.ItemIsMovable
            | QtWidgets.QGraphicsItem.ItemIsSelectable
            | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges
        )
        self.group.setSelected(True)

    def redo(self):
        # First time: create group. After undo: recreate it.
        if self.group is None or self.group.scene() is None:
            self._make_group()

    def undo(self):
        if self.group is not None and self.group.scene() is self.scene:
            # destroyItemGroup returns the children as top-level items again
            self.scene.destroyItemGroup(self.group)
            self.group = None
            # Re-select original items for nice UX
            for it in self.items:
                it.setSelected(True)


class UngroupItemsCmd(QtGui.QUndoCommand):
    """
    Ungroup one or more QGraphicsItemGroup objects.

    Undo: recreate the groups around the same children.
    Redo: destroy the groups again.
    """

    def __init__(
        self,
        scene: QtWidgets.QGraphicsScene,
        groups,
        text: str = "Ungroup items",
    ):
        super().__init__(text)
        self.scene = scene
        # Only keep actual groups
        self._orig_groups = [g for g in groups if isinstance(g, QtWidgets.QGraphicsItemGroup)]
        # Capture children per group so we can recreate groups on undo
        self._children_lists = [list(g.childItems()) for g in self._orig_groups]
        # Groups created during undo (so redo can destroy them again)
        self._current_groups: list[QtWidgets.QGraphicsItemGroup] = []

    def redo(self):
        # If we've undone before, we need to destroy the “current” groups.
        groups_to_destroy = self._current_groups or self._orig_groups
        for g in groups_to_destroy:
            if g is not None and g.scene() is self.scene:
                self.scene.destroyItemGroup(g)
        # After this, children are all top-level items.

        # Clear current groups reference; they no longer exist.
        self._current_groups = []

    def undo(self):
        # Re-create groups around the stored children.
        self._current_groups = []
        for children in self._children_lists:
            if not children:
                continue
            g = self.scene.createItemGroup(children)
            g.setFlags(
                QtWidgets.QGraphicsItem.ItemIsMovable
                | QtWidgets.QGraphicsItem.ItemIsSelectable
                | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges
            )
            self._current_groups.append(g)

        # Select all regrouped groups for nice UX
        for g in self._current_groups:
            g.setSelected(True)
