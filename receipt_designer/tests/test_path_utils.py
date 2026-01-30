"""
Tests for path normalization and portable asset transforms.
"""

import os
import sys
import pytest

from core.utils import normalize_path, dedupe_paths, make_asset_path_portable, resolve_asset_path


class TestNormalizePath:
    """Tests for path normalization."""

    def test_empty_path(self):
        """Empty string returns empty string."""
        assert normalize_path("") == ""

    def test_none_like_empty(self):
        """None-like values handled gracefully."""
        # Empty string is falsy
        assert normalize_path("") == ""

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_forward_vs_back_slashes(self):
        """Forward and backslashes normalize to same path on Windows."""
        path1 = "C:/Users/Test/file.json"
        path2 = "C:\\Users\\Test\\file.json"
        assert normalize_path(path1) == normalize_path(path2)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_case_insensitive(self):
        """Different casing normalizes to same path on Windows."""
        path1 = "C:\\Users\\Test\\FILE.json"
        path2 = "c:\\users\\test\\file.json"
        assert normalize_path(path1) == normalize_path(path2)

    def test_dot_segments_resolved(self):
        """.. and . segments are resolved."""
        # Create a path with .. that resolves to a simpler form
        path = os.path.join(os.getcwd(), "foo", "..", "bar", ".", "file.json")
        expected_end = os.path.join("bar", "file.json")
        normalized = normalize_path(path)
        assert normalized.endswith(os.path.normcase(expected_end))


class TestDedupePaths:
    """Tests for recent files deduplication."""

    def test_empty_list(self):
        """Empty list returns empty list."""
        assert dedupe_paths([]) == []

    def test_no_duplicates(self):
        """List without duplicates preserved."""
        paths = ["/a/b.json", "/c/d.json"]
        result = dedupe_paths(paths)
        assert len(result) == 2

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_duplicates_different_slashes(self):
        """Same path with different slashes dedupes to 1 on Windows."""
        paths = [
            "C:/Project/receipt.json",
            "C:\\Project\\receipt.json",
        ]
        result = dedupe_paths(paths)
        assert len(result) == 1
        # First occurrence wins
        assert result[0] == "C:/Project/receipt.json"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_duplicates_different_case(self):
        """Same path with different casing dedupes to 1 on Windows."""
        paths = [
            "C:\\Project\\Receipt.json",
            "c:\\project\\receipt.json",
            "C:\\PROJECT\\RECEIPT.JSON",
        ]
        result = dedupe_paths(paths)
        assert len(result) == 1

    def test_preserves_order(self):
        """First occurrence of duplicates is kept."""
        paths = ["/a/first.json", "/b/second.json", "/a/first.json"]
        result = dedupe_paths(paths)
        assert result == ["/a/first.json", "/b/second.json"]


class TestMakeAssetPathPortable:
    """Tests for converting absolute asset paths to relative."""

    def test_empty_asset_path(self):
        """Empty asset path returns empty."""
        assert make_asset_path_portable("", "C:/Project/receipt.json") == ""

    def test_empty_template_path(self):
        """No template path returns asset unchanged."""
        assert make_asset_path_portable("C:/Other/logo.png", "") == "C:/Other/logo.png"

    def test_already_relative(self):
        """Already relative path returns unchanged."""
        assert make_asset_path_portable("assets/logo.png", "C:/Project/receipt.json") == "assets/logo.png"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_asset_inside_template_dir(self):
        """Asset inside template directory becomes relative."""
        template_path = "C:\\Project\\receipt.json"
        asset_path = "C:\\Project\\assets\\logo.png"
        result = make_asset_path_portable(asset_path, template_path)
        # Should be relative path
        assert not os.path.isabs(result)
        assert "assets" in result
        assert "logo.png" in result

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_asset_outside_template_dir(self):
        """Asset outside template directory stays absolute."""
        template_path = "C:\\Project\\receipt.json"
        asset_path = "D:\\Other\\logo.png"
        result = make_asset_path_portable(asset_path, template_path)
        # Should remain absolute
        assert os.path.isabs(result)
        assert result == asset_path

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_different_drives_stays_absolute(self):
        """Assets on different drives stay absolute."""
        template_path = "C:\\Project\\receipt.json"
        asset_path = "D:\\Images\\logo.png"
        result = make_asset_path_portable(asset_path, template_path)
        assert os.path.isabs(result)


class TestResolveAssetPath:
    """Tests for resolving relative asset paths to absolute."""

    def test_empty_asset_path(self):
        """Empty asset path returns empty."""
        assert resolve_asset_path("", "C:/Project/receipt.json") == ""

    def test_already_absolute(self):
        """Already absolute path returns unchanged."""
        path = "C:/Images/logo.png"
        assert resolve_asset_path(path, "C:/Project/receipt.json") == path

    def test_windows_drive_path_on_any_platform(self):
        """Windows drive paths treated as absolute on any platform."""
        # These should NOT be joined to template directory
        assert resolve_asset_path("C:/Images/logo.png", "/home/user/template.json") == "C:/Images/logo.png"
        assert resolve_asset_path("D:\\Photos\\img.jpg", "/tmp/t.json") == "D:\\Photos\\img.jpg"

    def test_unc_path_on_any_platform(self):
        """UNC paths treated as absolute on any platform."""
        assert resolve_asset_path("\\\\server\\share\\logo.png", "/home/user/t.json") == "\\\\server\\share\\logo.png"
        assert resolve_asset_path("//server/share/logo.png", "/tmp/t.json") == "//server/share/logo.png"

    def test_no_template_path(self):
        """No template path returns asset unchanged."""
        assert resolve_asset_path("assets/logo.png", "") == "assets/logo.png"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_relative_resolved_to_absolute(self):
        """Relative path resolved against template directory."""
        template_path = "C:\\Project\\receipt.json"
        asset_path = "assets\\logo.png"
        result = resolve_asset_path(asset_path, template_path)
        assert os.path.isabs(result)
        expected = "C:\\Project\\assets\\logo.png"
        assert os.path.normcase(result) == os.path.normcase(expected)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_roundtrip_portable_then_resolve(self):
        """Portable path can be resolved back to original."""
        template_path = "C:\\Project\\receipt.json"
        original_asset = "C:\\Project\\assets\\logo.png"

        # Make portable
        portable = make_asset_path_portable(original_asset, template_path)
        assert not os.path.isabs(portable)

        # Resolve back
        resolved = resolve_asset_path(portable, template_path)
        assert os.path.normcase(resolved) == os.path.normcase(original_asset)
