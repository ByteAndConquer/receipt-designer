"""
UI Integration test for autosave/recovery.

This test exercises the actual UI code paths for autosave and recovery.
It is OPTIONAL and requires explicit opt-in via environment variable.

Requirements to run:
- Set RUN_QT_TESTS=1 environment variable
- PySide6 must be installed

Run locally:
    RUN_QT_TESTS=1 py -m pytest -m qt_integration -v

In CI:
- Skipped by default (RUN_QT_TESTS not set)
- Opt-in by setting RUN_QT_TESTS=1 in the CI job
"""

import os
import json

# ============================================================================
# Environment setup: Use offscreen Qt platform for headless testing
# ============================================================================
# Set offscreen platform if not already set (allows headless testing)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# ============================================================================
# Skip conditions
# ============================================================================

# Check if Qt tests are explicitly enabled
_qt_tests_enabled = os.environ.get("RUN_QT_TESTS") == "1"

# Skip entire module if RUN_QT_TESTS is not set
if not _qt_tests_enabled:
    pytest.skip(
        "Qt integration tests disabled. Set RUN_QT_TESTS=1 to enable.",
        allow_module_level=True
    )

# Skip if PySide6 is not available
PySide6 = pytest.importorskip("PySide6", reason="PySide6 required for UI integration tests")

from PySide6 import QtCore, QtWidgets

# Mark all tests in this module with qt_integration marker
pytestmark = pytest.mark.qt_integration


def _try_create_qapp():
    """Try to create a QApplication, return None if it fails."""
    try:
        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([])
        return app
    except Exception as e:
        return None


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def qapp():
    """Create or reuse QApplication for the test module."""
    app = _try_create_qapp()
    if app is None:
        pytest.skip("Could not create QApplication (no display available)")
    yield app
    # Don't quit the app - it may be shared


@pytest.fixture
def autosave_path():
    """Get the autosave file path and ensure cleanup."""
    temp_dir = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.TempLocation
    )
    path = os.path.join(temp_dir, "receipt_designer_autosave.json")

    # Clean up before test
    if os.path.exists(path):
        os.remove(path)

    yield path

    # Clean up after test
    if os.path.exists(path):
        os.remove(path)


# ============================================================================
# Tests
# ============================================================================

class TestUIAutosaveRecovery:
    """
    Integration tests for the autosave/recovery UI code paths.

    These tests instantiate the actual MainWindow and exercise
    the real autosave and recovery methods.
    """

    def test_autosave_creates_file_with_all_element_types(self, qapp, autosave_path):
        """
        Test that autosave correctly saves text and shape elements.

        This exercises the actual UI code path:
        1. Create MainWindow
        2. Add elements via the same methods the UI uses
        3. Call _auto_save() directly
        4. Verify file exists with correct element kinds
        """
        from receipt_designer.ui.main_window_impl import MainWindow as MainWindowImpl
        from receipt_designer.core.models import Element
        from receipt_designer.ui.items import GItem, create_item_from_element

        # Create the main window (but don't show it)
        window = MainWindowImpl()

        try:
            # Add a text element via the scene (simulating UI add)
            text_elem = Element(
                kind="text", text="Test Text", x=10, y=20, w=100, h=30
            )
            text_item = GItem(text_elem)
            text_item.undo_stack = window.undo_stack
            window.scene.addItem(text_item)
            text_item.setPos(text_elem.x, text_elem.y)

            # Add a line element
            line_elem = Element(
                kind="line", x=50, y=100, w=80, h=40,
                stroke_color="#FF0000", stroke_px=2.0
            )
            line_item = create_item_from_element(line_elem)
            line_item.undo_stack = window.undo_stack
            window.scene.addItem(line_item)

            # Mark as having unsaved changes (normally done by scene.changed signal)
            window._has_unsaved_changes = True

            # Force autosave (don't wait for timer)
            window._auto_save()

            # Verify autosave file was created
            assert os.path.exists(autosave_path), "Autosave file should exist"

            # Verify file contents
            with open(autosave_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            assert "elements" in data, "Autosave should contain elements"
            assert len(data["elements"]) == 2, "Should have 2 elements"

            kinds = {e["kind"] for e in data["elements"]}
            assert "text" in kinds, "Should have text element"
            assert "line" in kinds, "Should have line element"

        finally:
            # Mark as saved to prevent closeEvent from autosaving again
            window._has_unsaved_changes = False
            window.close()
            # Clean up autosave file to avoid affecting other tests
            if os.path.exists(autosave_path):
                os.remove(autosave_path)

    def test_recovery_restores_all_element_types(self, qapp, autosave_path):
        """
        Test that recovery correctly restores text and shape elements.

        This exercises:
        1. Create MainWindow (no autosave file exists - no recovery prompt)
        2. Create autosave data and load it directly (simulating what recovery does)
        3. Verify elements are reconstructed with correct types
        """
        from receipt_designer.ui.main_window_impl import MainWindow as MainWindowImpl
        from receipt_designer.ui.items import GItem, GLineItem, GRectItem, SERIALIZABLE_ITEM_TYPES
        from receipt_designer.core.models import Template

        # Create autosave data (but don't write to file yet - avoid recovery prompt)
        autosave_data = {
            "width_mm": 80.0,
            "height_mm": 75.0,
            "dpi": 203,
            "margins_mm": [4.0, 0.0, 4.0, 0.0],
            "elements": [
                {"kind": "text", "text": "Recovery Test", "x": 10, "y": 10, "w": 100, "h": 30, "z": 1},
                {"kind": "line", "x": 20, "y": 50, "w": 60, "h": 30, "stroke_color": "#0000FF", "stroke_px": 1.5, "z": 2},
                {"kind": "rect", "x": 30, "y": 100, "w": 50, "h": 40, "stroke_color": "#00FF00", "z": 3},
            ],
            "guides": [],
            "grid": None,
            "name": "Test Template",
            "version": "1.0",
            "variables": {"variables": {}},
        }

        # Create the main window FIRST (no autosave file = no recovery dialog)
        window = MainWindowImpl()

        try:
            # Clear the scene (window init may have default items)
            window.scene.clear()

            # Now simulate what recovery does: load data and rebuild scene
            from receipt_designer.ui.items import create_item_from_element

            window.template = Template.from_dict(autosave_data)

            # Rebuild scene using the factory (same code path as recovery)
            for e in window.template.elements:
                item = create_item_from_element(e)
                item.undo_stack = window.undo_stack
                if hasattr(item, "_main_window"):
                    item._main_window = window
                window.scene.addItem(item)

            # Count serializable items in scene
            items = [it for it in window.scene.items() if isinstance(it, SERIALIZABLE_ITEM_TYPES)]
            assert len(items) == 3, f"Should have 3 elements, got {len(items)}"

            # Verify correct types were created
            item_types = [type(it).__name__ for it in items]
            assert "GItem" in item_types, "Should have GItem (for text)"
            assert "GLineItem" in item_types, "Should have GLineItem"
            assert "GRectItem" in item_types, "Should have GRectItem"

        finally:
            window.close()

    def test_close_event_triggers_autosave(self, qapp, autosave_path):
        """
        Test that closing the window with unsaved changes triggers autosave.
        """
        from receipt_designer.ui.main_window_impl import MainWindow as MainWindowImpl
        from receipt_designer.core.models import Element
        from receipt_designer.ui.items import GItem

        window = MainWindowImpl()

        try:
            # Add an element
            elem = Element(kind="text", text="Close Test", x=0, y=0, w=50, h=20)
            item = GItem(elem)
            window.scene.addItem(item)

            # Mark unsaved
            window._has_unsaved_changes = True

            # Trigger close (this should call _auto_save)
            window.close()

            # Verify autosave was created
            assert os.path.exists(autosave_path), "Autosave should be created on close"

            with open(autosave_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            assert len(data.get("elements", [])) >= 1, "Should have at least 1 element"

        finally:
            # Window already closed, but ensure cleanup
            pass
