"""
core/utils.py - Pure utility functions for path handling and normalization.

These are extracted from MainWindow methods for testability.
"""

import os
import re
from typing import List


def _is_windows_absolute(path: str) -> bool:
    """Check if path is Windows-absolute (drive letter or UNC), even on non-Windows."""
    if not path:
        return False
    # Drive letter: C:\ or C:/
    if re.match(r'^[a-zA-Z]:[\\/]', path):
        return True
    # UNC path: \\server\share or //server/share
    if re.match(r'^[\\/]{2}[^\\/]+[\\/]+[^\\/]+', path):
        return True
    return False


def normalize_path(path: str) -> str:
    """
    Normalize a file path for consistent comparison and deduplication.

    On Windows this ensures paths like 'C:/foo/bar.json' and 'c:\\foo\\BAR.JSON'
    are recognized as the same file.

    Returns normalized path for comparison; original path is kept for display.
    """
    if not path:
        return ""
    # Expand user home directory if present
    path = os.path.expanduser(path)
    # Convert to absolute path
    path = os.path.abspath(path)
    # Normalize separators and resolve .. / .
    path = os.path.normpath(path)
    # Normalize case on Windows (lowercase on Windows, unchanged on Unix)
    path = os.path.normcase(path)
    return path


def dedupe_paths(paths: List[str]) -> List[str]:
    """
    Remove duplicate paths from a list based on normalized paths.

    Preserves order (first occurrence wins) and keeps display-friendly paths.
    """
    seen_normalized = set()
    deduped = []
    for path in paths:
        norm = normalize_path(path)
        if norm and norm not in seen_normalized:
            seen_normalized.add(norm)
            deduped.append(path)
    return deduped


def make_asset_path_portable(asset_path: str, template_path: str) -> str:
    """
    Convert an absolute asset path to relative if it's inside the template directory.

    Args:
        asset_path: The asset file path (e.g., image_path from an Element)
        template_path: The path to the template JSON file being saved

    Returns:
        Relative path if asset is under template_dir, else original path unchanged.
    """
    if not asset_path or not template_path:
        return asset_path

    # Skip if already relative
    if not os.path.isabs(asset_path):
        return asset_path

    try:
        template_dir = os.path.dirname(os.path.abspath(template_path))
        asset_abs = os.path.abspath(asset_path)

        # Normalize for comparison (handles case on Windows)
        template_dir_norm = os.path.normcase(os.path.normpath(template_dir))
        asset_abs_norm = os.path.normcase(os.path.normpath(asset_abs))

        # Check if asset is under template directory
        # Use os.path.commonpath for reliable prefix checking
        try:
            common = os.path.commonpath([template_dir_norm, asset_abs_norm])
            if common == template_dir_norm:
                # Asset is under template dir - make relative
                rel_path = os.path.relpath(asset_abs, template_dir)
                return rel_path
        except ValueError:
            # Different drives on Windows (e.g., C: vs D:)
            pass

    except Exception:
        # Any error - keep original path
        pass

    return asset_path


def resolve_asset_path(asset_path: str, template_path: str) -> str:
    """
    Resolve an asset path, converting relative paths to absolute based on template location.

    Args:
        asset_path: The asset file path from the template (may be relative or absolute)
        template_path: The path to the template JSON file being loaded

    Returns:
        Absolute path if input was relative, else original path unchanged.
    """
    if not asset_path:
        return asset_path

    # If already absolute, return as-is (check both native and Windows-style)
    if os.path.isabs(asset_path) or _is_windows_absolute(asset_path):
        return asset_path

    # Relative path - resolve against template directory
    if not template_path:
        return asset_path

    try:
        template_dir = os.path.dirname(os.path.abspath(template_path))
        resolved = os.path.normpath(os.path.join(template_dir, asset_path))
        return resolved
    except Exception:
        # Any error - keep original path
        return asset_path
