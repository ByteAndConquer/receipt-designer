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
