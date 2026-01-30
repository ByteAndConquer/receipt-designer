from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import json
from PySide6.QtCore import QSettings


# Storage key (matches main_window_impl.py convention)
PROFILES_KEY = "printer/profiles_json"


@dataclass
class PrinterProfile:
    """
    A named wrapper around the existing printer_cfg dict.

    - name: what shows up in the UI ("Kitchen TM-T88IV", "Front Desk 58mm")
    - config: your existing printer_cfg dict (interface, host, port, dpi, etc.)
    """
    name: str = "Default"
    config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PrinterProfile":
        name = data.get("name", "Unnamed")
        cfg = data.get("config", {}) or {}
        return cls(name=name, config=cfg)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "config": self.config or {},
        }


def _settings() -> QSettings:
    """
    Return QSettings using QCoreApplication org/app names.
    This respects the app-level setOrganizationName/setApplicationName calls.
    """
    return QSettings()


def load_profiles(
    load_single_fn: Optional[Callable[[], Dict[str, Any]]] = None
) -> List[PrinterProfile]:
    """
    Load printer profiles from QSettings.

    If no profiles are stored yet, this will optionally call
    `load_single_fn()` (your old load_printer_settings) to migrate
    the legacy single printer_cfg into a 'Default' profile.
    """
    s = _settings()
    raw = s.value(PROFILES_KEY, "", type=str)

    if raw:
        try:
            arr = json.loads(raw)
            profiles = [PrinterProfile.from_dict(d) for d in arr]
            if profiles:
                return profiles
        except Exception:
            # If parsing fails, fall back to migration logic below.
            pass

    # Migration / fallback: build a single "Default" profile
    cfg: Dict[str, Any] = {}
    name = "Default"

    if load_single_fn is not None:
        try:
            cfg = load_single_fn() or {}
            name = cfg.get("profile") or "Default"
        except Exception:
            cfg = {}

    return [PrinterProfile(name=name, config=cfg)]


def save_profiles(profiles: List[PrinterProfile]) -> None:
    """
    Persist printer profiles to QSettings as JSON.
    """
    s = _settings()
    raw = json.dumps([p.to_dict() for p in profiles], indent=2)
    s.setValue(PROFILES_KEY, raw)
