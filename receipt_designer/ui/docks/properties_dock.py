# receipt_designer/ui/docks/properties_dock.py
"""Builder for the Properties dock widget."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from ..properties import PropertiesPanel

if TYPE_CHECKING:
    from ..host_protocols import DocksHost


def build_properties_dock(mw: DocksHost) -> QtWidgets.QDockWidget:
    """
    Create the Properties dock widget (with scroll wrapper) and attach it to *mw*.

    Sets ``mw.props``.
    Returns the ``QDockWidget`` so the orchestrator can tabify it.
    """
    mw.props = PropertiesPanel(mw)
    mw.props.set_undo_stack(mw.undo_stack)

    props_scroll = QtWidgets.QScrollArea()
    props_scroll.setWidget(mw.props)
    props_scroll.setWidgetResizable(True)
    props_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    props_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

    dock = QtWidgets.QDockWidget("Properties", mw)
    dock.setObjectName("PropertiesDock")
    dock.setWidget(props_scroll)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    return dock
