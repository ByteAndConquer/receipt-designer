# receipt_designer/ui/docks/__init__.py
"""
Dock widget orchestration.

Individual dock builders live in sibling modules; this file calls them
in the right order and wires up cross-dock concerns (tabify, signals).

This module must NOT import main_window_impl to avoid circular imports.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ..toolbox import Toolbox
from .layers_dock import build_layers_dock
from .properties_dock import build_properties_dock
from .variables_dock import build_variables_dock

if TYPE_CHECKING:
    from ..host_protocols import DocksHost


def build_docks(mw: DocksHost) -> None:
    """
    Create all dock widgets (toolbox, layers, properties, variables) and
    attach them to *mw*.

    Sets attributes on *mw*: toolbox, layer_list, props, variable_panel,
    dock_variables.
    """

    # LEFT: Toolbox
    mw.toolbox = Toolbox(mw)
    mw.toolbox.add_text.connect(mw.add_text)
    mw.toolbox.add_barcode.connect(mw.add_barcode)
    mw.toolbox.add_image.connect(mw.add_image)
    mw.toolbox.add_line.connect(mw.add_line)
    mw.toolbox.add_arrow.connect(mw.add_arrow)
    mw.toolbox.add_rect.connect(mw.add_rect)
    mw.toolbox.add_circle.connect(mw.add_circle)
    mw.toolbox.add_star.connect(mw.add_star)
    mw.toolbox.add_diamond.connect(mw.add_diamond)

    dock_left = QtWidgets.QDockWidget("Toolbox", mw)
    dock_left.setObjectName("ToolboxDock")
    dock_left.setWidget(mw.toolbox)
    mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock_left)

    # RIGHT: individual dock builders
    dock_layers = build_layers_dock(mw)
    dock_props = build_properties_dock(mw)
    dock_vars = build_variables_dock(mw)

    # Tabify all right-side panels together
    mw.tabifyDockWidget(dock_layers, dock_props)
    mw.tabifyDockWidget(dock_props, dock_vars)

    # Show Properties by default
    dock_props.raise_()

    # Connect variable changes to view updates
    mw.variable_panel.variables_changed.connect(
        lambda: mw.view.viewport().update()
    )

    # Keep panels in sync
    mw.scene.selectionChanged.connect(mw._on_selection_changed)
    mw.scene.changed.connect(mw._on_scene_changed)
    mw.props.element_changed.connect(mw._on_props_element_changed)


def update_view_menu(mw: DocksHost) -> None:
    """Add dock toggle actions to View menu (called after docks are built)."""
    for action in mw.menuBar().actions():
        if action.text() == "&View":
            view_menu = action.menu()
            if view_menu:
                view_menu.addSeparator()

                if hasattr(mw, 'dock_variables'):
                    act_variables = mw.dock_variables.toggleViewAction()
                    act_variables.setText("Variables Panel")
                    view_menu.addAction(act_variables)
            break
