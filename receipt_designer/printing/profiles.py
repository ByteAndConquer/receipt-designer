from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import json
from PySide6.QtCore import QSettings


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
    # Use the same org/app you use elsewhere for QSettings.
    # Adjust if your app uses different strings.
    return QSettings("ReceiptDesigner", "ReceiptDesigner")


def load_profiles(load_single_fn=None) -> List[PrinterProfile]:
    """
    Load printer profiles from QSettings.

    If no profiles are stored yet, this will optionally call
    `load_single_fn()` (your old load_printer_settings) to migrate
    the legacy single printer_cfg into a 'Default' profile.
    """
    s = _settings()
    raw = s.value("printer_profiles", "", type=str)

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
    cfg = load_single_fn() if load_single_fn is not None else None
    if cfg is None:
        cfg = {}

    return [PrinterProfile(name="Default", config=cfg)]


def save_profiles(profiles: List[PrinterProfile]) -> None:
    """
    Persist printer profiles to QSettings as JSON.
    """
    s = _settings()
    raw = json.dumps([p.to_dict() for p in profiles], indent=2)
    s.setValue("printer_profiles", raw)
