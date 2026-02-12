# receipt_designer/ui/host_protocols.py
"""
Typing-only Protocol definitions for MainWindow attribute coupling.

Each Protocol describes the *minimal* subset of MainWindow that a given
extracted module actually reads, writes, or calls.  These are **static
guardrails only** — they are never checked at runtime.

Rules
-----
- Protocols live here; extracted modules import them under TYPE_CHECKING.
- Only stdlib ``typing`` / ``collections.abc`` types are used.
- Qt types are forward-referenced (strings) or imported under
  TYPE_CHECKING to avoid import-time cost.
- This module must NOT import ``main_window_impl``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from PySide6 import QtCore, QtGui, QtWidgets

    from ..core.models import Template


# ── helpers ──────────────────────────────────────────────────────────────────

class _HasScene(Protocol):
    """Common: exposes a QGraphicsScene."""

    scene: "QtWidgets.QGraphicsScene"


class _HasUndoStack(Protocol):
    """Common: exposes a QUndoStack."""

    undo_stack: "QtGui.QUndoStack"


class _HasTemplate(Protocol):
    """Common: exposes a Template model."""

    template: "Template"


class _HasStatusBar(Protocol):
    """Common: has statusBar() -> QStatusBar."""

    def statusBar(self) -> "QtWidgets.QStatusBar": ...


# ── Per-module Protocols ─────────────────────────────────────────────────────

class CanvasHost(
    _HasScene,
    _HasTemplate,
    Protocol,
):
    """Attributes used by ``canvas/controller.py``."""

    view: "QtWidgets.QGraphicsView"
    _inline_editor: object
    _column_guides: list

    # Methods called by canvas/controller
    def _mark_unsaved(self) -> None: ...
    def installEventFilter(self, obj: "QtCore.QObject") -> None: ...
    def setCentralWidget(self, widget: "QtWidgets.QWidget") -> None: ...


class DocksHost(
    _HasScene,
    _HasUndoStack,
    Protocol,
):
    """Attributes used by ``docks/`` package."""

    view: "QtWidgets.QGraphicsView"
    props: object
    variable_panel: object
    dock_variables: "QtWidgets.QDockWidget"
    toolbox: object
    layer_list: object

    # Toolbox signal targets
    def add_text(self) -> None: ...
    def add_barcode(self) -> None: ...
    def add_image(self) -> None: ...
    def add_line(self) -> None: ...
    def add_arrow(self) -> None: ...
    def add_rect(self) -> None: ...
    def add_circle(self) -> None: ...
    def add_star(self) -> None: ...
    def add_diamond(self) -> None: ...

    # Selection/scene sync
    def _on_selection_changed(self) -> None: ...
    def _on_scene_changed(self, _region_list: object = ...) -> None: ...
    def _on_props_element_changed(self, *args: object) -> None: ...

    # QMainWindow methods
    def addDockWidget(
        self, area: "QtCore.Qt.DockWidgetArea", dock: "QtWidgets.QDockWidget"
    ) -> None: ...
    def tabifyDockWidget(
        self, first: "QtWidgets.QDockWidget", second: "QtWidgets.QDockWidget"
    ) -> None: ...
    def menuBar(self) -> "QtWidgets.QMenuBar": ...


class ActionsHost(
    _HasScene,
    _HasUndoStack,
    _HasTemplate,
    Protocol,
):
    """Attributes used by ``actions.py``."""

    printer_cfg: dict
    settings: "QtCore.QSettings"

    # Widgets set by build_toolbars_and_menus (declared so type-checkers
    # know they exist after the call)
    sb_darkness: "QtWidgets.QSpinBox"
    cb_cut: "QtWidgets.QComboBox"
    profile_combo: "QtWidgets.QComboBox"
    cb_w_mm: "QtWidgets.QComboBox"
    cb_h_mm: "QtWidgets.QComboBox"
    sb_baseline_mm: "QtWidgets.QDoubleSpinBox"
    action_margins: "QtGui.QAction"
    action_dark_mode: "QtGui.QAction"
    recent_menu: "QtWidgets.QMenu"
    act_align_use_margins: "QtGui.QAction"
    _shortcut_delete: "QtGui.QShortcut"
    _shortcut_duplicate: "QtGui.QShortcut"

    # File operations
    def save_template(self) -> None: ...
    def load_template(self) -> None: ...
    def preview_print(self) -> None: ...
    def print_now(self) -> None: ...
    def configure_printer(self) -> None: ...
    def quick_action(self, cmd: str) -> None: ...
    def export_png(self) -> None: ...
    def export_pdf(self) -> None: ...

    # Settings callbacks
    def _on_darkness_changed(self, value: int = ...) -> None: ...
    def _on_cut_changed(self, label: str = ...) -> None: ...
    def _refresh_profile_combo(self) -> None: ...
    def _on_profile_changed(self, index: int = ...) -> None: ...
    def _on_toggle_margins(self, checked: bool = ...) -> None: ...
    def _toggle_dark_mode(self, checked: bool = ...) -> None: ...
    def _refresh_recent_menu(self) -> None: ...

    # Layout operations
    def _align_selected(self, mode: str) -> None: ...
    def _distribute_selected(self, axis: str) -> None: ...
    def _group_selected(self) -> None: ...
    def _ungroup_selected(self) -> None: ...
    def _change_z_order(self, mode: str) -> None: ...
    def _lock_selected(self) -> None: ...
    def _unlock_selected(self) -> None: ...
    def _hide_selected(self) -> None: ...
    def _show_all_hidden(self) -> None: ...
    def _apply_baseline_to_selected(self) -> None: ...
    def _delete_selected_items(self) -> None: ...
    def _duplicate_selected_items(self) -> None: ...
    def _set_duplicate_offset_dialog(self) -> None: ...
    def _set_column_guides_dialog(self) -> None: ...
    def _clear_column_guides(self) -> None: ...
    def _apply_preset(self, name: str) -> None: ...
    def _show_keyboard_shortcuts_dialog(self) -> None: ...
    def update_paper(self) -> None: ...

    # Insert element operations
    def add_text(self) -> None: ...
    def add_barcode(self) -> None: ...
    def add_image(self) -> None: ...
    def add_line(self) -> None: ...
    def add_rect(self) -> None: ...
    def add_circle(self) -> None: ...
    def add_star(self) -> None: ...
    def add_arrow(self) -> None: ...
    def add_diamond(self) -> None: ...

    # QMainWindow methods
    def addToolBar(self, toolbar: "QtWidgets.QToolBar") -> None: ...
    def addToolBarBreak(self) -> None: ...
    def menuBar(self) -> "QtWidgets.QMenuBar": ...
    def close(self) -> bool: ...


class PersistenceHost(
    _HasScene,
    _HasUndoStack,
    _HasTemplate,
    _HasStatusBar,
    Protocol,
):
    """Attributes used by ``persistence.py``."""

    _current_file_path: str | None
    _has_unsaved_changes: bool
    settings: "QtCore.QSettings"
    recent_menu: "QtWidgets.QMenu"

    def update_paper(self) -> None: ...
    def _refresh_layers_safe(self) -> None: ...
    def _refresh_variable_panel(self) -> None: ...
    def _clear_column_guides(self) -> None: ...


class PresetsHost(
    _HasScene,
    _HasUndoStack,
    _HasTemplate,
    _HasStatusBar,
    Protocol,
):
    """Attributes used by ``presets.py``."""

    def update_paper(self) -> None: ...
    def _refresh_layers_safe(self) -> None: ...


class LayoutHost(
    _HasScene,
    _HasUndoStack,
    _HasStatusBar,
    Protocol,
):
    """Attributes used by ``layout_ops.py``."""

    _last_duplicate_offset: "QtCore.QPointF"
    act_align_use_margins: "QtGui.QAction"
    sb_baseline_mm: "QtWidgets.QDoubleSpinBox"

    def _refresh_layers_safe(self) -> None: ...
