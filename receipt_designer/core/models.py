from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Optional, Any, Dict


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
        return Element(**d)


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
        return GuideLine(**d)


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
        return GuideGrid(**d)


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
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Template":
        t = Template(
            width_mm=d.get("width_mm", 80.0),
            height_mm=d.get("height_mm", .0),
            dpi=d.get("dpi", 203),
            margins_mm=tuple(d.get("margins_mm", (5.0, 5.0, 5.0, 5.0))),
            name=d.get("name", "Untitled"),
            version=d.get("version", "1.0"),
        )
        t.elements = [Element.from_dict(x) for x in d.get("elements", [])]
        t.guides = [GuideLine.from_dict(x) for x in d.get("guides", [])]
        g = d.get("grid")
        if g:
            t.grid = GuideGrid.from_dict(g)
        return t
