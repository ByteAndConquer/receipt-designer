# receipt_designer/ui/docks/variables_dock.py
"""Builder for the Variables dock widget."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ..variables import VariablePanel

if TYPE_CHECKING:
    from ..host_protocols import DocksHost


def build_variables_dock(mw: DocksHost) -> QtWidgets.QDockWidget:
    """
    Create the Variables dock widget and attach it to *mw*.

    Sets ``mw.variable_panel`` and ``mw.dock_variables``.
    Returns the ``QDockWidget`` so the orchestrator can tabify it.
    """
    mw.variable_panel = VariablePanel(mw)

    dock = QtWidgets.QDockWidget("Variables", mw)
    dock.setObjectName("VariablesDock")
    dock.setWidget(mw.variable_panel)
    dock.setFeatures(
        QtWidgets.QDockWidget.DockWidgetMovable |
        QtWidgets.QDockWidget.DockWidgetFloatable
    )
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

    # Store reference on mw so update_view_menu() can find it
    mw.dock_variables = dock
    return dock
