"""
Tests for variable resolution (VariableManager and system variables).
"""

import re
from datetime import datetime
from unittest.mock import patch

import pytest

from core.models import VariableManager


class TestVariableManagerBasic:
    """Basic VariableManager functionality."""

    def test_create_has_defaults(self):
        """New VariableManager has default variables."""
        vm = VariableManager()
        # VariableManager initializes with useful defaults
        assert "store_name" in vm.get_all_variables()
        assert "store_address" in vm.get_all_variables()

    def test_set_and_get(self):
        """Can set and get a variable."""
        vm = VariableManager()
        vm.set_variable("custom_var", "Test Value")
        assert vm.get_variable("custom_var") == "Test Value"

    def test_get_missing_returns_empty_string(self):
        """Getting undefined variable returns empty string."""
        vm = VariableManager()
        assert vm.get_variable("nonexistent") == ""

    def test_delete_variable(self):
        """Can delete a variable."""
        vm = VariableManager()
        vm.set_variable("temp", "value")
        assert vm.delete_variable("temp") is True
        assert vm.get_variable("temp") == ""  # Returns empty string when missing

    def test_delete_nonexistent_returns_false(self):
        """Deleting nonexistent variable returns False."""
        vm = VariableManager()
        assert vm.delete_variable("definitely_not_a_variable") is False


class TestVariableResolution:
    """Tests for {{var:name}} token resolution."""

    def test_resolve_defined_variable(self):
        """Defined variable is replaced."""
        vm = VariableManager()
        vm.set_variable("name", "Alice")
        result = vm.resolve_text("Hello {{var:name}}!")
        assert result == "Hello Alice!"

    def test_resolve_multiple_variables(self):
        """Multiple variables in same text resolved."""
        vm = VariableManager()
        vm.set_variable("first", "John")
        vm.set_variable("last", "Doe")
        result = vm.resolve_text("Name: {{var:first}} {{var:last}}")
        assert result == "Name: John Doe"

    def test_resolve_same_variable_twice(self):
        """Same variable used twice is resolved both times."""
        vm = VariableManager()
        vm.set_variable("x", "X")
        result = vm.resolve_text("{{var:x}} and {{var:x}}")
        assert result == "X and X"

    def test_missing_variable_stays_literal(self):
        """Missing variable token stays as literal text (current policy)."""
        vm = VariableManager()
        result = vm.resolve_text("Value: {{var:undefined}}")
        # Per Fix 2: unresolved tokens stay as-is
        assert result == "Value: {{var:undefined}}"

    def test_mixed_defined_and_undefined(self):
        """Mix of defined and undefined variables handled correctly."""
        vm = VariableManager()
        vm.set_variable("known", "KNOWN")
        result = vm.resolve_text("A={{var:known}} B={{var:unknown}}")
        assert result == "A=KNOWN B={{var:unknown}}"

    def test_empty_text(self):
        """Empty text returns empty."""
        vm = VariableManager()
        assert vm.resolve_text("") == ""
        assert vm.resolve_text(None) is None

    def test_no_variables_in_text(self):
        """Text without variables unchanged."""
        vm = VariableManager()
        text = "Plain text without variables"
        assert vm.resolve_text(text) == text

    def test_variable_name_validation_pattern(self):
        """Variable names must match pattern [a-zA-Z_][a-zA-Z0-9_]*."""
        vm = VariableManager()
        vm.set_variable("valid_name", "ok")
        vm.set_variable("_underscore", "ok")
        vm.set_variable("CamelCase", "ok")
        vm.set_variable("name123", "ok")

        # These should resolve
        assert vm.resolve_text("{{var:valid_name}}") == "ok"
        assert vm.resolve_text("{{var:_underscore}}") == "ok"
        assert vm.resolve_text("{{var:CamelCase}}") == "ok"
        assert vm.resolve_text("{{var:name123}}") == "ok"

        # Invalid patterns should not match (stay as literal)
        # Note: The regex won't match these anyway
        assert vm.resolve_text("{{var:123start}}") == "{{var:123start}}"
        assert vm.resolve_text("{{var:has-dash}}") == "{{var:has-dash}}"


class TestVariableManagerSerialization:
    """Tests for to_dict / from_dict."""

    def test_roundtrip(self):
        """Variables survive to_dict / from_dict roundtrip."""
        vm = VariableManager()
        vm.set_variable("store", "My Store")
        vm.set_variable("phone", "555-1234")

        data = vm.to_dict()
        vm2 = VariableManager.from_dict(data)

        assert vm2.get_variable("store") == "My Store"
        assert vm2.get_variable("phone") == "555-1234"

    def test_from_dict_empty(self):
        """from_dict with empty dict creates empty manager."""
        vm = VariableManager.from_dict({})
        assert vm.get_all_variables() == {}

    def test_from_dict_missing_variables_key(self):
        """from_dict handles missing 'variables' key."""
        vm = VariableManager.from_dict({"other": "data"})
        assert vm.get_all_variables() == {}


class TestSystemVariables:
    """
    Tests for system variable placeholders.

    Note: System variables are resolved in GItem._resolve_text(), not VariableManager.
    These tests verify the expected system variable patterns exist.
    """

    def test_system_variable_patterns(self):
        """System variable patterns are well-formed."""
        # These are the documented system variables
        system_vars = [
            "{{date}}",
            "{{time}}",
            "{{datetime}}",
            "{{year}}",
            "{{month}}",
            "{{month_name}}",
            "{{day}}",
            "{{weekday}}",
            "{{hour}}",
            "{{minute}}",
            "{{second}}",
        ]
        # They should not be confused with user variables
        user_var_pattern = re.compile(r'\{\{var:([a-zA-Z_][a-zA-Z0-9_]*)\}\}')
        for var in system_vars:
            assert user_var_pattern.search(var) is None, f"{var} matched user var pattern"

    def test_user_var_pattern_matches_correctly(self):
        """User variable pattern matches expected format."""
        pattern = re.compile(r'\{\{var:([a-zA-Z_][a-zA-Z0-9_]*)\}\}')

        # Should match
        assert pattern.search("{{var:name}}") is not None
        assert pattern.search("{{var:_private}}") is not None
        assert pattern.search("{{var:CamelCase}}") is not None
        assert pattern.search("{{var:with123}}") is not None

        # Should not match
        assert pattern.search("{{date}}") is None
        assert pattern.search("{{time}}") is None
        assert pattern.search("{{var:}}") is None
        assert pattern.search("{{var:123}}") is None
