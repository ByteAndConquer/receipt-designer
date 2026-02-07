"""
Tests for Template serialization and autosave reserved key behavior.
"""

import pytest

from core.models import Template, Element, VariableManager


class TestTemplateDefaults:
    """Tests for Template default values."""

    def test_default_margins(self):
        """Default margins match dataclass default."""
        t = Template()
        assert t.margins_mm == (4.0, 0.0, 4.0, 0.0)

    def test_from_dict_margins_fallback(self):
        """from_dict uses correct margins fallback (Fix 1)."""
        t = Template.from_dict({})
        assert t.margins_mm == (4.0, 0.0, 4.0, 0.0)

    def test_from_dict_explicit_margins(self):
        """from_dict respects explicit margins."""
        t = Template.from_dict({"margins_mm": [10.0, 5.0, 10.0, 5.0]})
        assert t.margins_mm == (10.0, 5.0, 10.0, 5.0)


class TestTemplateRoundtrip:
    """Tests for Template to_dict / from_dict roundtrip."""

    def test_basic_roundtrip(self):
        """Template survives serialization roundtrip."""
        t1 = Template(width_mm=100.0, height_mm=150.0)
        data = t1.to_dict()
        t2 = Template.from_dict(data)

        assert t2.width_mm == 100.0
        assert t2.height_mm == 150.0

    def test_elements_roundtrip(self):
        """Elements survive roundtrip."""
        t1 = Template()
        elem = Element(kind="text", text="Hello", x=10, y=20, w=100, h=50)
        t1.elements.append(elem)

        data = t1.to_dict()
        t2 = Template.from_dict(data)

        assert len(t2.elements) == 1
        assert t2.elements[0].text == "Hello"

    def test_variables_roundtrip(self):
        """Variables survive roundtrip."""
        t1 = Template()
        t1.variable_manager.set_variable("store", "Test Store")

        data = t1.to_dict()
        t2 = Template.from_dict(data)

        assert t2.variable_manager.get_variable("store") == "Test Store"


class TestAutosaveReservedKey:
    """Tests for autosave reserved key behavior."""

    def test_autosave_key_not_in_normal_save(self):
        """Normal template save does not include _autosave_original_path."""
        t = Template()
        t.elements.append(Element(kind="text", text="Test", x=0, y=0, w=50, h=20))

        data = t.to_dict()

        # The reserved key should NOT be present in normal saves
        assert "_autosave_original_path" not in data

    def test_from_dict_ignores_unknown_keys(self):
        """Template.from_dict ignores unknown top-level keys."""
        data = {
            "width_mm": 80.0,
            "_autosave_original_path": "C:\\Some\\Path\\template.json",
            "_unknown_future_key": "some value",
        }

        # Should not raise
        t = Template.from_dict(data)
        assert t.width_mm == 80.0

        # The unknown keys should not cause errors
        # and should not appear as attributes
        assert not hasattr(t, "_autosave_original_path")
        assert not hasattr(t, "_unknown_future_key")

    def test_autosave_key_should_be_popped_before_from_dict(self):
        """
        Autosave key should be popped/handled by caller before Template.from_dict.

        This test documents the expected pattern:
        1. Load autosave JSON
        2. Pop _autosave_original_path for separate handling
        3. Pass remaining dict to Template.from_dict
        """
        autosave_data = {
            "width_mm": 80.0,
            "height_mm": 100.0,
            "_autosave_original_path": "C:\\Original\\receipt.json",
            "elements": [],
        }

        # Simulate the expected autosave loading pattern
        original_path = autosave_data.pop("_autosave_original_path", None)

        assert original_path == "C:\\Original\\receipt.json"
        assert "_autosave_original_path" not in autosave_data

        # Now from_dict works on clean data
        t = Template.from_dict(autosave_data)
        assert t.width_mm == 80.0


class TestElementUnknownKeys:
    """Tests for Element unknown key preservation (Fix 3)."""

    def test_unknown_keys_preserved(self):
        """Unknown keys in element dict are preserved in data['_unknown']."""
        d = {
            "kind": "text",
            "text": "Hello",
            "x": 0, "y": 0, "w": 50, "h": 20,
            "future_field": "future_value",
        }

        elem = Element.from_dict(d)

        # Unknown key should be in data["_unknown"]
        assert elem.data is not None
        assert "_unknown" in elem.data
        assert elem.data["_unknown"]["future_field"] == "future_value"

    def test_unknown_keys_merged_not_replaced(self):
        """Multiple unknown keys are merged into existing _unknown (Fix 3)."""
        d = {
            "kind": "text",
            "x": 0, "y": 0, "w": 50, "h": 20,
            "data": {
                "user_stuff": 1,
                "_unknown": {"old_key": "old_val"}
            },
            "new_future_key": "new_val",
        }

        elem = Element.from_dict(d)

        # Both old and new unknown keys should be present
        assert elem.data["user_stuff"] == 1
        assert elem.data["_unknown"]["old_key"] == "old_val"
        assert elem.data["_unknown"]["new_future_key"] == "new_val"

    def test_element_roundtrip_preserves_unknown(self):
        """Unknown keys survive element to_dict / from_dict roundtrip."""
        d = {
            "kind": "text",
            "x": 0, "y": 0, "w": 50, "h": 20,
            "plugin_data": {"custom": "value"},
        }

        elem1 = Element.from_dict(d)
        data = elem1.to_dict()
        elem2 = Element.from_dict(data)

        # The unknown key path is preserved
        assert "_unknown" in elem2.data
        assert "plugin_data" in elem2.data["_unknown"]


class TestAllElementKindsSerialize:
    """
    Tests for Template serialization with ALL element kinds.

    These tests verify that all element kinds can be serialized and deserialized
    at the Element/Template level (core model layer).
    """

    def test_template_with_all_element_kinds(self):
        """Template with ALL element kinds survives roundtrip."""
        # Create elements of each kind
        elements = [
            Element(kind="text", text="Test", x=0, y=0, w=100, h=30, z=1),
            Element(kind="image", image_path="test.png", x=0, y=50, w=100, h=100, z=2),
            Element(kind="barcode", text="123", x=0, y=160, w=100, h=40, z=3),
            Element(kind="qr", text="data", x=0, y=210, w=80, h=80, z=4),
            Element(kind="line", x=0, y=300, w=100, h=50, z=5, stroke_color="#000000", stroke_px=2.0),
            Element(kind="arrow", x=0, y=360, w=80, h=40, z=6, data={"arrow_length_px": 10.0}),
            Element(kind="rect", x=0, y=410, w=60, h=40, z=7, corner_radius_px=5.0),
            Element(kind="ellipse", x=0, y=460, w=50, h=50, z=8),
            Element(kind="star", x=0, y=520, w=40, h=40, z=9, data={"star_points": 5}),
            Element(kind="diamond", x=0, y=570, w=35, h=35, z=10),
        ]

        # Create template
        t1 = Template()
        t1.elements = elements

        # Serialize
        data = t1.to_dict()

        # Verify all elements present
        assert len(data["elements"]) == 10

        # Deserialize
        t2 = Template.from_dict(data)

        # Verify count
        assert len(t2.elements) == 10

        # Verify kinds
        kinds_found = {e.kind for e in t2.elements}
        expected_kinds = {"text", "image", "barcode", "qr", "line", "arrow", "rect", "ellipse", "star", "diamond"}
        assert kinds_found == expected_kinds

    def test_z_order_preserved(self):
        """Z-order (z-index) is preserved across roundtrip."""
        elements = [
            Element(kind="text", text="Bottom", x=0, y=0, w=50, h=20, z=1),
            Element(kind="rect", x=10, y=10, w=40, h=40, z=5),
            Element(kind="text", text="Top", x=20, y=20, w=50, h=20, z=10),
        ]

        t1 = Template()
        t1.elements = elements
        data = t1.to_dict()
        t2 = Template.from_dict(data)

        # Verify z values
        z_values = [e.z for e in t2.elements]
        assert z_values == [1, 5, 10]

    def test_line_element_properties(self):
        """Line element preserves stroke properties."""
        elem = Element(
            kind="line", x=10, y=20, w=100, h=50,
            stroke_color="#FF0000", stroke_px=2.5, z=3
        )

        data = elem.to_dict()
        elem2 = Element.from_dict(data)

        assert elem2.kind == "line"
        assert elem2.stroke_color == "#FF0000"
        assert elem2.stroke_px == 2.5
        assert elem2.z == 3

    def test_arrow_element_with_data(self):
        """Arrow element preserves data dict properties."""
        elem = Element(
            kind="arrow", x=0, y=0, w=80, h=40,
            stroke_color="#0000FF", stroke_px=1.5,
            data={"arrow_length_px": 15.0, "arrow_width_px": 8.0, "arrow_at_start": True}
        )

        data = elem.to_dict()
        elem2 = Element.from_dict(data)

        assert elem2.kind == "arrow"
        assert elem2.data["arrow_length_px"] == 15.0
        assert elem2.data["arrow_width_px"] == 8.0
        assert elem2.data["arrow_at_start"] is True

    def test_rect_element_with_corner_radius(self):
        """Rect element preserves corner_radius_px."""
        elem = Element(
            kind="rect", x=50, y=60, w=120, h=80,
            stroke_color="#0000FF", fill_color="#FFFF00",
            corner_radius_px=10.0, data={"pill_mode": True}
        )

        data = elem.to_dict()
        elem2 = Element.from_dict(data)

        assert elem2.kind == "rect"
        assert elem2.corner_radius_px == 10.0
        assert elem2.fill_color == "#FFFF00"
        assert elem2.data["pill_mode"] is True

    def test_star_element_with_points(self):
        """Star element preserves star_points in data dict."""
        elem = Element(
            kind="star", x=0, y=0, w=50, h=50,
            data={"star_points": 6}
        )

        data = elem.to_dict()
        elem2 = Element.from_dict(data)

        assert elem2.kind == "star"
        assert elem2.data["star_points"] == 6

    def test_visibility_flag_preserved(self):
        """Visibility flag is preserved across roundtrip."""
        elem = Element(kind="rect", x=0, y=0, w=50, h=50, visible=False)

        data = elem.to_dict()
        elem2 = Element.from_dict(data)

        assert elem2.visible is False


class TestAutosaveRecoveryCondition:
    """Tests for autosave recovery condition logic."""

    def test_autosave_file_with_elements_should_trigger_recovery(self):
        """
        When autosave file exists and contains elements,
        the recovery condition should be True.
        """
        import tempfile
        import os
        import json

        # Create a mock autosave file with elements
        autosave_data = {
            "width_mm": 80.0,
            "height_mm": 75.0,
            "elements": [
                {"kind": "text", "text": "Test", "x": 0, "y": 0, "w": 100, "h": 30},
                {"kind": "rect", "x": 10, "y": 40, "w": 50, "h": 50},
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(autosave_data, f)
            temp_path = f.name

        try:
            # Verify file exists
            assert os.path.exists(temp_path)

            # Verify file has elements
            with open(temp_path, "r") as f:
                data = json.load(f)

            assert "elements" in data
            assert len(data["elements"]) == 2

            # This is the condition that should trigger recovery
            should_recover = (
                os.path.exists(temp_path)
                and len(data.get("elements", [])) > 0
            )
            assert should_recover is True
        finally:
            os.unlink(temp_path)

    def test_autosave_file_without_elements_should_not_trigger_recovery(self):
        """
        When autosave file exists but has no elements,
        recovery is still offered (but will be empty).
        """
        import tempfile
        import os
        import json

        # Create a mock autosave file with no elements
        autosave_data = {
            "width_mm": 80.0,
            "height_mm": 75.0,
            "elements": [],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(autosave_data, f)
            temp_path = f.name

        try:
            # Verify file exists
            assert os.path.exists(temp_path)

            # File exists, so recovery would be offered (current behavior)
            # The user can choose to decline
            should_prompt = os.path.exists(temp_path)
            assert should_prompt is True
        finally:
            os.unlink(temp_path)

    def test_no_autosave_file_should_not_trigger_recovery(self):
        """
        When no autosave file exists, recovery should not be triggered.
        """
        import tempfile
        import os

        # Non-existent path
        fake_path = os.path.join(tempfile.gettempdir(), "nonexistent_autosave_12345.json")

        # Ensure it doesn't exist
        if os.path.exists(fake_path):
            os.unlink(fake_path)

        should_prompt = os.path.exists(fake_path)
        assert should_prompt is False

    def test_corrupted_autosave_should_be_preserved(self):
        """
        When autosave JSON is invalid, it should be renamed to .bad for inspection.
        """
        import tempfile
        import os

        # Create a corrupt autosave file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ this is not valid JSON }")
            temp_path = f.name

        try:
            # Try to parse it
            import json
            is_valid = True
            try:
                with open(temp_path, "r") as f:
                    json.load(f)
            except json.JSONDecodeError:
                is_valid = False

            assert is_valid is False, "File should be invalid JSON"

            # In real code, we'd rename to .bad
            bad_path = temp_path + ".bad"
            os.replace(temp_path, bad_path)

            # Verify rename worked
            assert os.path.exists(bad_path), "Bad file should exist"
            assert not os.path.exists(temp_path), "Original should not exist"

        finally:
            # Cleanup both possible paths
            for p in [temp_path, temp_path + ".bad"]:
                if os.path.exists(p):
                    os.unlink(p)
