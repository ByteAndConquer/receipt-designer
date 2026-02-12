# receipt_designer/ui/common.py
"""
Tiny shared helpers used by 2+ UI modules.

These exist solely to eliminate copy-pasted guard blocks.
Keep this module small and dependency-free (no mw, no Qt widgets).
"""
from __future__ import annotations

from .views import PX_PER_MM


def px_per_mm_factor() -> float:
    """Return PX_PER_MM as a float, with a safe fallback of 1.0."""
    try:
        return float(PX_PER_MM) if PX_PER_MM else 1.0
    except Exception:
        return 1.0


def unpack_margins_mm(source: object) -> tuple[float, float, float, float]:
    """
    Read ``margins_mm`` from *source* (scene, template, or any object) and
    return ``(left, top, right, bottom)`` in millimetres.

    Falls back to ``(0, 0, 0, 0)`` on any error.
    """
    margins_mm = getattr(source, "margins_mm", (0.0, 0.0, 0.0, 0.0))
    try:
        ml, mt, mr, mb = margins_mm
        return (float(ml), float(mt), float(mr), float(mb))
    except Exception:
        return (0.0, 0.0, 0.0, 0.0)
