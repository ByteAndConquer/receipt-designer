"""
UI smoke and contract tests — fast, headless, no clicking.

These tests verify that extracted UI modules import cleanly and that
MainWindow wires up its key components (menus, toolbars, docks) without
crashing.  They catch broken imports, missing attributes, and wiring
regressions after refactors.

Requirements to run:
    Set RUN_QT_TESTS=1 environment variable.

Run locally:
    RUN_QT_TESTS=1 pytest tests/test_ui_smoke.py -v
    # PowerShell:
    $env:RUN_QT_TESTS="1"; pytest tests/test_ui_smoke.py -v
"""

import os

# ── Headless setup (must precede any PySide6 import) ──────────────────
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# ── Skip gate ─────────────────────────────────────────────────────────
_qt_tests_enabled = os.environ.get("RUN_QT_TESTS") == "1"
if not _qt_tests_enabled:
    pytest.skip(
        "Qt smoke tests disabled. Set RUN_QT_TESTS=1 to enable.",
        allow_module_level=True,
    )

PySide6 = pytest.importorskip("PySide6", reason="PySide6 required for UI smoke tests")

from PySide6 import QtCore, QtGui, QtWidgets

pytestmark = pytest.mark.qt_integration


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    """Create or reuse a QApplication for the entire module."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    if app is None:
        pytest.skip("Could not create QApplication (no display available)")
    yield app


@pytest.fixture(scope="module")
def window(qapp):
    """Construct a MainWindow once and share it across all tests."""
    from receipt_designer.ui.main_window import MainWindow

    win = MainWindow()
    yield win
    # Prevent autosave side-effects on teardown
    win._has_unsaved_changes = False
    win.close()


# ══════════════════════════════════════════════════════════════════════
# Test 1 — Import smoke
# ══════════════════════════════════════════════════════════════════════

class TestImportSmoke:
    """Every extracted UI module must be importable without side effects."""

    def test_import_actions(self):
        from receipt_designer.ui.actions import build_toolbars_and_menus
        assert callable(build_toolbars_and_menus)

    def test_import_docks(self):
        from receipt_designer.ui.docks import build_docks, update_view_menu
        assert callable(build_docks)
        assert callable(update_view_menu)

    def test_import_canvas_controller(self):
        from receipt_designer.ui.canvas.controller import (
            build_scene_view,
            setup_inline_editor,
            update_paper,
        )
        assert callable(build_scene_view)
        assert callable(setup_inline_editor)
        assert callable(update_paper)

    def test_import_dialogs(self):
        from receipt_designer.ui.dialogs import (
            PrintPreviewDialog,
            show_keyboard_shortcuts_dialog,
            show_duplicate_offset_dialog,
            show_printer_config_dialog,
            show_column_guides_dialog,
        )
        assert PrintPreviewDialog is not None
        assert callable(show_keyboard_shortcuts_dialog)
        assert callable(show_duplicate_offset_dialog)
        assert callable(show_printer_config_dialog)
        assert callable(show_column_guides_dialog)

    def test_import_persistence(self):
        from receipt_designer.ui.persistence import save_template, load_template
        assert callable(save_template)
        assert callable(load_template)

    def test_import_presets(self):
        from receipt_designer.ui.presets import apply_preset
        assert callable(apply_preset)

    def test_import_layout_ops(self):
        from receipt_designer.ui.layout_ops import align_selected, group_selected
        assert callable(align_selected)
        assert callable(group_selected)

    def test_import_host_protocols(self):
        from receipt_designer.ui.host_protocols import (
            CanvasHost,
            DocksHost,
            ActionsHost,
            PersistenceHost,
            PresetsHost,
            LayoutHost,
        )
        # Protocols are classes
        assert isinstance(CanvasHost, type)
        assert isinstance(DocksHost, type)
        assert isinstance(ActionsHost, type)
        assert isinstance(PersistenceHost, type)
        assert isinstance(PresetsHost, type)
        assert isinstance(LayoutHost, type)


# ══════════════════════════════════════════════════════════════════════
# Test 2 — MainWindow construct / close
# ══════════════════════════════════════════════════════════════════════

class TestMainWindowLifecycle:
    """MainWindow must instantiate and close without crashing."""

    def test_construct_and_close(self, qapp):
        from receipt_designer.ui.main_window import MainWindow

        win = MainWindow()
        try:
            assert win is not None
            assert isinstance(win, QtWidgets.QMainWindow)
        finally:
            win._has_unsaved_changes = False
            win.close()


# ══════════════════════════════════════════════════════════════════════
# Test 3 — Actions contract (light)
# ══════════════════════════════════════════════════════════════════════

class TestActionsContract:
    """Toolbar / menu wiring must be present after construction."""

    def test_menu_bar_exists(self, window):
        mb = window.menuBar()
        assert mb is not None
        assert isinstance(mb, QtWidgets.QMenuBar)

    def test_menu_bar_has_menus(self, window):
        """At least File, Edit, View menus should exist."""
        menu_texts = [a.text() for a in window.menuBar().actions()]
        # Use stripped / de-amped versions for tolerance
        clean = [t.replace("&", "") for t in menu_texts]
        for expected in ("File", "Edit", "View"):
            assert expected in clean, f"Menu '{expected}' not found in {clean}"

    def test_has_at_least_one_toolbar(self, window):
        toolbars = window.findChildren(QtWidgets.QToolBar)
        assert len(toolbars) >= 1, "MainWindow should have at least one toolbar"

    def test_undo_stack_exists(self, window):
        assert hasattr(window, "undo_stack")
        assert isinstance(window.undo_stack, QtGui.QUndoStack)


# ══════════════════════════════════════════════════════════════════════
# Test 4 — Docks contract (light)
# ══════════════════════════════════════════════════════════════════════

class TestDocksContract:
    """Dock widgets for layers, properties, variables must be wired."""

    def _find_dock(self, window, object_name: str) -> QtWidgets.QDockWidget:
        """Find a dock widget by its objectName."""
        for dock in window.findChildren(QtWidgets.QDockWidget):
            if dock.objectName() == object_name:
                return dock
        return None

    def test_layers_dock_exists(self, window):
        dock = self._find_dock(window, "LayersDock")
        assert dock is not None, "LayersDock not found"
        assert isinstance(dock, QtWidgets.QDockWidget)

    def test_properties_dock_exists(self, window):
        dock = self._find_dock(window, "PropertiesDock")
        assert dock is not None, "PropertiesDock not found"
        assert isinstance(dock, QtWidgets.QDockWidget)

    def test_variables_dock_exists(self, window):
        dock = self._find_dock(window, "VariablesDock")
        assert dock is not None, "VariablesDock not found"
        assert isinstance(dock, QtWidgets.QDockWidget)

    def test_toolbox_dock_exists(self, window):
        dock = self._find_dock(window, "ToolboxDock")
        assert dock is not None, "ToolboxDock not found"
        assert isinstance(dock, QtWidgets.QDockWidget)

    def test_right_docks_area(self, window):
        """Layers, Properties, Variables should be in the right dock area."""
        for name in ("LayersDock", "PropertiesDock", "VariablesDock"):
            dock = self._find_dock(window, name)
            assert dock is not None, f"{name} not found"
            area = window.dockWidgetArea(dock)
            assert area == QtCore.Qt.RightDockWidgetArea, (
                f"{name} should be in RightDockWidgetArea, got {area}"
            )

    def test_toolbox_dock_left_area(self, window):
        """Toolbox should be in the left dock area."""
        dock = self._find_dock(window, "ToolboxDock")
        assert dock is not None
        area = window.dockWidgetArea(dock)
        assert area == QtCore.Qt.LeftDockWidgetArea, (
            f"ToolboxDock should be in LeftDockWidgetArea, got {area}"
        )

    def test_scene_and_view_exist(self, window):
        """Scene and view must be wired after construction."""
        assert hasattr(window, "scene")
        assert isinstance(window.scene, QtWidgets.QGraphicsScene)
        assert hasattr(window, "view")
        assert isinstance(window.view, QtWidgets.QGraphicsView)
