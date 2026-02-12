# receipt_designer/ui/canvas/controller.py
"""
Canvas controller: scene/view creation, inline editor setup, paper updates.

All builders receive the MainWindow instance to avoid circular imports —
this module must NOT import main_window_impl.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from ..views import RulerView
from ..inline_editor import CanvasTextEditorOverlay

if TYPE_CHECKING:
    from ..host_protocols import CanvasHost


def build_scene_view(mw: CanvasHost) -> None:
    """
    Create the QGraphicsScene + RulerView, wrap in a central widget,
    and attach to *mw*.

    Sets attributes on *mw*: scene, view.
    """
    mw.scene = QtWidgets.QGraphicsScene(mw)
    mw.view = RulerView(mw)
    mw.view.setScene(mw.scene)
    mw.view.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
    # Make canvas white so red dotted margins are visible
    mw.view.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
    # Force margins visible by default
    if hasattr(mw.view, "setShowMargins"):
        mw.view.setShowMargins(True)
    else:
        setattr(mw.view, "show_margins", True)

    # Rubberband drag for multi-selection
    mw.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)

    # Ensure the view/viewport can take focus
    mw.view.setFocusPolicy(QtCore.Qt.StrongFocus)
    mw.view.viewport().setFocusPolicy(QtCore.Qt.StrongFocus)

    # Keyboard handling on BOTH view and viewport
    mw.view.installEventFilter(mw)
    mw.view.viewport().installEventFilter(mw)

    central = QtWidgets.QWidget(mw)
    lay = QtWidgets.QVBoxLayout(central)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(mw.view)
    mw.setCentralWidget(central)

    mw.scene.changed.connect(mw._mark_unsaved)


def setup_inline_editor(mw: CanvasHost) -> None:
    """
    Set up the in-place text editor for canvas elements.

    Sets attribute on *mw*: _inline_editor.
    """
    mw._inline_editor = CanvasTextEditorOverlay(mw.view)

    # Update editor geometry when view scrolls or zooms
    mw.view.horizontalScrollBar().valueChanged.connect(
        mw._inline_editor.updateGeometry
    )
    mw.view.verticalScrollBar().valueChanged.connect(
        mw._inline_editor.updateGeometry
    )
    mw.view.viewTransformChanged.connect(
        mw._inline_editor.updateGeometry
    )


def update_paper(mw: CanvasHost) -> None:
    """
    Synchronize scene rect, margins, DPI, and column guides with
    the current *mw*.template.
    """
    w = float(mw.template.width_px)
    h = float(mw.template.height_px)
    mw.scene.setSceneRect(0, 0, w, h)

    # expose properties that RulerView expects
    mw.scene.setProperty("paper_width", w)
    mw.scene.setProperty("paper_height", h)
    mw.scene.setProperty("dpi", mw.template.dpi)

    # margins_mm on scene: (left, top, right, bottom)
    mw.scene.margins_mm = getattr(
        mw.template,
        "margins_mm",
        (4.0, 0.0, 4.0, 0.0),
    )

    # Keep column guides spanning the full paper height
    if hasattr(mw, "_column_guides"):
        for g in mw._column_guides:
            line = g.line()
            g.setLine(line.x1(), 0, line.x2(), h)

    mw.view.viewport().update()
