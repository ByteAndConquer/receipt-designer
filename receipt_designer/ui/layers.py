from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from .items import (
    GItem,
    GRectItem,
    GEllipseItem,
    GStarItem,
    GLineItem,
    GArrowItem,
    GDiamondItem,
)

class LayerList(QtWidgets.QTreeWidget):
    """
    Layer list view for the current QGraphicsScene.

    - Shows top-level items + QGraphicsItemGroup as tree nodes.
    - Group children appear as nested items under the group node.
    - Selection is synced both ways:
        * scene.selectionChanged -> _sync_from_scene()
        * tree selectionChanged  -> _sync_to_scene()
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._scene: QtWidgets.QGraphicsScene | None = None
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        # When the user clicks in the tree, update scene selection.
        self.itemSelectionChanged.connect(self._on_tree_selection_changed)

        self.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred,
            QtWidgets.QSizePolicy.Expanding,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_scene(self, scene: QtWidgets.QGraphicsScene | None) -> None:
        """Attach a QGraphicsScene and rebuild the tree."""
        # Disconnect from old scene
        if self._scene is not None:
            try:
                self._scene.selectionChanged.disconnect(self._on_scene_selection_changed)
            except Exception:
                pass

        self._scene = scene

        # Connect to new scene
        if self._scene is not None:
            try:
                self._scene.selectionChanged.connect(self._on_scene_selection_changed)
            except Exception:
                pass

        self.refresh()


    def refresh(self) -> None:
        """
        Rebuilds the tree to reflect the current scene.
        Must NOT change the scene selection.
        """
        self.blockSignals(True)
        try:
            self.clear()
            if self._scene is None:
                return

            try:
                self._rebuild()
            except RuntimeError:
                # Underlying C++ scene object is gone; drop the reference.
                self._scene = None
                self.clear()
                return
        finally:
            self.blockSignals(False)



    # ------------------------------------------------------------------
    # Internal: rebuild tree from scene
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        if self._scene is None:
            self.clear()
            return

        self.clear()
        scene = self._scene

        # Collect all groups and their children so we can nest them
        groups: list[QtWidgets.QGraphicsItemGroup] = []
        all_children: set[QtWidgets.QGraphicsItem] = set()

        for item in scene.items():
            if isinstance(item, QtWidgets.QGraphicsItemGroup):
                groups.append(item)
                for ch in item.childItems():
                    all_children.add(ch)

        # Map group -> tree widget item
        group_nodes: dict[QtWidgets.QGraphicsItemGroup, QtWidgets.QTreeWidgetItem] = {}

        # First, create tree nodes for each group
        for g in groups:
            label = self._label_for_group(g)
            node = QtWidgets.QTreeWidgetItem(self, [label])
            node.setData(0, QtCore.Qt.ItemDataRole.UserRole, g)
            node.setExpanded(True)
            group_nodes[g] = node

        # Now add children under their group node
        for g, node in group_nodes.items():
            for ch in g.childItems():
                child_label = self._label_for_item(ch)
                child_node = QtWidgets.QTreeWidgetItem(node, [child_label])
                child_node.setData(0, QtCore.Qt.ItemDataRole.UserRole, ch)

        # Finally, add non-group, non-child items as top-level
        for item in scene.items():
            if isinstance(item, QtWidgets.QGraphicsItemGroup):
                continue
            if item in all_children:
                continue
            label = self._label_for_item(item)
            node = QtWidgets.QTreeWidgetItem(self, [label])
            node.setData(0, QtCore.Qt.ItemDataRole.UserRole, item)

        self.expandAll()


    # ------------------------------------------------------------------
    # Label helpers
    # ------------------------------------------------------------------

    def _label_for_group(self, group: QtWidgets.QGraphicsItemGroup) -> str:
        # Try a friendly label; otherwise just "Group"
        name = getattr(group, "name", None)
        if name:
            return f"Group: {name}"
        return "Group"

    def _label_for_item(self, item: QtWidgets.QGraphicsItem) -> str:
        # If it has an "elem" with kind or text, use that
        elem = getattr(item, "elem", None)
        if elem is not None:
            kind = getattr(elem, "kind", None)
            text = getattr(elem, "text", None)
            if kind and text:
                short = (text or "").strip()
                if len(short) > 24:
                    short = short[:21] + "..."
                return f"{kind.capitalize()}: {short}" if short else kind.capitalize()
            if kind:
                return kind.capitalize()

        # Fallback: type-based label
        cls_name = type(item).__name__
        return cls_name

    # ------------------------------------------------------------------
    # Selection sync
    # ------------------------------------------------------------------

    def _on_scene_selection_changed(self) -> None:
        """Slot connected to scene.selectionChanged."""
        self._sync_from_scene()

    def _sync_from_scene(self) -> None:
        """Update tree selection to match what's selected in the scene."""
        if self._scene is None:
            return

        try:
            selected_items = set(self._scene.selectedItems())
        except RuntimeError:
            # Scene has been deleted; stop using it.
            self._scene = None
            return

        # Block signals so we don't trigger _on_tree_selection_changed
        self.blockSignals(True)
        try:
            def walk(parent_item: QtWidgets.QTreeWidgetItem | None):
                count = self.topLevelItemCount() if parent_item is None else parent_item.childCount()
                for i in range(count):
                    it = self.topLevelItem(i) if parent_item is None else parent_item.child(i)
                    gfx_item = it.data(0, QtCore.Qt.ItemDataRole.UserRole)
                    it.setSelected(gfx_item in selected_items)
                    if it.childCount() > 0:
                        walk(it)

            walk(None)
        finally:
            self.blockSignals(False)


    def _on_tree_selection_changed(self) -> None:
        """When user clicks in the tree, apply that selection to the scene."""
        if self._scene is None:
            return

        # Don’t recurse back into our own slot endlessly
        try:
            self._scene.blockSignals(True)

            # Clear scene selection
            for it in self._scene.items():
                it.setSelected(False)

            # Apply tree selection
            for item in self.selectedItems():
                gfx_item = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
                if isinstance(gfx_item, QtWidgets.QGraphicsItem):
                    gfx_item.setSelected(True)
        finally:
            self._scene.blockSignals(False)
