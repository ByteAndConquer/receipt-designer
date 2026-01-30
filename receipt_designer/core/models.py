from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields
from typing import List, Tuple, Optional, Any, Dict
import re


# ---------- Core element model ----------

@dataclass
class Element:
    # geometry
    kind: str                       # "text" | "image" | "qr" | "barcode" | "rect" | "ellipse" | "line"
    x: float
    y: float
    w: float
    h: float
    rotation: float = 0.0

    # text props
    text: str = ""
    font_family: str = "Arial"
    font_size: int = 12
    bold: bool = False
    italic: bool = False
    halign: str = "left"            # left|center|right
    valign: str = "top"             # top|middle|bottom
    wrap: bool = True
    shrink_to_fit: bool = False
    max_lines: int = 0              # 0 = unlimited
    baseline_px: int = 0            # 0 = off

    # image props
    image_path: str = ""
    keep_aspect: bool = True

    # barcode / qr props
    barcode_type: str = "CODE128"   # CODE128|CODE39|EAN13|UPCA|ITF14|PDF417|DATAMATRIX|AZTEC
    barcode_hr_text: bool = True
    barcode_scale: float = 1.0
    qr_ec_level: str = "M"          # L|M|Q|H

    # shapes/lines
    stroke_px: float = 1.0
    corner_radius_px: float = 0.0
    fill_color: str = "#000000"
    stroke_color: str = "#000000"

    # misc
    visible: bool = True
    locked: bool = False              # legacy full-lock flag
    lock_mode: str = "none"           # "none" | "position" | "style" | "full"
    z: int = 0

    # arbitrary extras for forward-compat
    data: Dict[str, Any] = field(default_factory=dict)

    # ---- helpers used by scene items / persistence ----
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Element":
        """
        Create an Element from a dict, handling unknown/missing keys gracefully.

        - Unknown keys are preserved in `data` field (forward compatibility)
        - Missing optional keys use dataclass defaults
        - Missing required keys (kind, x, y, w, h) use safe fallbacks
        """
        # Get the set of valid field names for Element
        valid_fields = {f.name for f in fields(Element)}

        # Filter to only known fields
        filtered = {k: v for k, v in d.items() if k in valid_fields}

        # Preserve unknown keys in the `data` dict (forward compatibility)
        # This ensures future/plugin data is not silently lost
        unknown_keys = {k: v for k, v in d.items() if k not in valid_fields}
        if unknown_keys:
            # Merge into existing data dict, or create new one
            existing_data = filtered.get("data", {}) or {}
            # Merge unknown keys into existing _unknown dict (don't replace)
            existing_unknown = existing_data.get("_unknown", {}) or {}
            existing_unknown.update(unknown_keys)
            existing_data["_unknown"] = existing_unknown
            filtered["data"] = existing_data

        # Provide safe defaults for required fields if missing
        # (These have no defaults in the dataclass, so we must handle them)
        if "kind" not in filtered:
            filtered["kind"] = "text"  # Safe default
        if "x" not in filtered:
            filtered["x"] = 0.0
        if "y" not in filtered:
            filtered["y"] = 0.0
        if "w" not in filtered:
            filtered["w"] = 50.0
        if "h" not in filtered:
            filtered["h"] = 20.0

        return Element(**filtered)


# ---------- Guide/grid models ----------

@dataclass
class GuideLine:
    x1: float
    y1: float
    x2: float
    y2: float
    color: str = "#888888"
    dashed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GuideLine":
        """Create a GuideLine from dict, ignoring unknown keys."""
        valid_fields = {f.name for f in fields(GuideLine)}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        # Provide defaults for required fields
        if "x1" not in filtered:
            filtered["x1"] = 0.0
        if "y1" not in filtered:
            filtered["y1"] = 0.0
        if "x2" not in filtered:
            filtered["x2"] = 0.0
        if "y2" not in filtered:
            filtered["y2"] = 0.0
        return GuideLine(**filtered)


@dataclass
class GuideGrid:
    rows: int = 1
    cols: int = 1
    gutter_x_px: float = 0.0
    gutter_y_px: float = 0.0
    inset_px: float = 0.0
    visible: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GuideGrid":
        """Create a GuideGrid from dict, ignoring unknown keys."""
        valid_fields = {f.name for f in fields(GuideGrid)}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        # All GuideGrid fields have defaults, so no required field handling needed
        return GuideGrid(**filtered)


# ---------- Variable Manager ----------

class VariableManager:
    """
    Manages user-defined template variables.
    System variables (date, time) are still handled by GItem._resolve_text()
    """
    
    def __init__(self):
        self.variables: dict[str, str] = {}
        self._init_default_variables()
    
    def _init_default_variables(self):
        """Initialize some useful default variables"""
        self.variables = {
            "store_name": "My Store",
            "store_address": "123 Main St",
            "store_phone": "(555) 123-4456",
            "receipt_footer": "Thank you for your business!",
        }
    
    def set_variable(self, name: str, value: str):
        """Set a variable value"""
        self.variables[name] = value
    
    def get_variable(self, name: str) -> str:
        """Get a variable value, or empty string if not found"""
        return self.variables.get(name, "")
    
    def delete_variable(self, name: str) -> bool:
        """Delete a variable. Returns True if deleted."""
        if name in self.variables:
            del self.variables[name]
            return True
        return False
    
    def get_all_variables(self) -> dict[str, str]:
        """Get all variables"""
        return self.variables.copy()
    
    def resolve_text(self, text: str) -> str:
        """
        Resolve user variables in text.
        Format: {{var:variable_name}}

        Example:
            text = "Welcome to {{var:store_name}}"
            result = "Welcome to My Store"

        If a variable is not defined, the token is left as-is (e.g., "{{var:unknown}}"
        remains in the output) to make missing variables visible to the user.
        """
        if not text:
            return text

        # Pattern for {{var:name}}
        pattern = r'\{\{var:([a-zA-Z_][a-zA-Z0-9_]*)\}\}'

        def replace_var(match):
            var_name = match.group(1)
            if var_name in self.variables:
                return self.variables[var_name]
            # Leave unresolved tokens as literal text so user can see what's missing
            return match.group(0)

        return re.sub(pattern, replace_var, text)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON"""
        return {
            "variables": self.variables.copy()
        }
    
    @staticmethod
    def from_dict(data: dict) -> "VariableManager":
        """Load from dictionary - returns a NEW VariableManager instance"""
        vm = VariableManager()
        # Replace default variables with loaded ones
        vm.variables = data.get("variables", {}).copy()
        return vm


# ---------- Template / document ----------

@dataclass
class Template:
    # page / printer
    width_mm: float = 80.0
    height_mm: float = 75.0
    dpi: int = 203
    margins_mm: tuple[float, float, float, float] = (4.0, 0.0, 4.0, 0.0)

    # content
    elements: List[Element] = field(default_factory=list)
    guides: List[GuideLine] = field(default_factory=list)
    grid: Optional[GuideGrid] = None

    # metadata
    name: str = "Untitled"
    version: str = "1.0"
    
    # variables
    variable_manager: VariableManager = field(default_factory=VariableManager)

    # ---- convenience ----
    @property
    def px_per_mm(self) -> float:
        return float(self.dpi) / 25.4

    @property
    def width_px(self) -> float:
        return self.width_mm * self.px_per_mm

    @property
    def height_px(self) -> float:
        return self.height_mm * self.px_per_mm

    def to_dict(self) -> Dict[str, Any]:
        return {
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "dpi": self.dpi,
            "margins_mm": list(self.margins_mm),
            "elements": [e.to_dict() for e in self.elements],
            "guides": [g.to_dict() for g in self.guides],
            "grid": self.grid.to_dict() if self.grid else None,
            "name": self.name,
            "version": self.version,
            "variables": self.variable_manager.to_dict(),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Template":
        # Use same default as dataclass field: (4.0, 0.0, 4.0, 0.0)
        t = Template(
            width_mm=d.get("width_mm", 80.0),
            height_mm=d.get("height_mm", 75.0),
            dpi=d.get("dpi", 203),
            margins_mm=tuple(d.get("margins_mm", (4.0, 0.0, 4.0, 0.0))),
            name=d.get("name", "Untitled"),
            version=d.get("version", "1.0"),
        )
        t.elements = [Element.from_dict(x) for x in d.get("elements", [])]
        t.guides = [GuideLine.from_dict(x) for x in d.get("guides", [])]
        g = d.get("grid")
        if g:
            t.grid = GuideGrid.from_dict(g)
        
        # Load variables if present
        if "variables" in d:
            t.variable_manager = VariableManager.from_dict(d["variables"])
        
        return t