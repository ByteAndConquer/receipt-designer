# receipt_designer/ui/docks/layers_dock.py
"""Builder for the Layers dock widget."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ..layers import LayerList

if TYPE_CHECKING:
    from ..host_protocols import DocksHost


def build_layers_dock(mw: DocksHost) -> QtWidgets.QDockWidget:
    """
    Create the Layers dock widget and attach it to *mw*.

    Sets ``mw.layer_list``.
    Returns the ``QDockWidget`` so the orchestrator can tabify it.
    """
    mw.layer_list = LayerList(mw)
    mw.layer_list.set_scene(mw.scene)

    dock = QtWidgets.QDockWidget("Layers", mw)
    dock.setObjectName("LayersDock")
    dock.setWidget(mw.layer_list)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    return dock
