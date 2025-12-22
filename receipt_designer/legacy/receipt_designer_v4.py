#!/usr/bin/env python3
"""
Receipt Designer & Printer — Pro MVP v4.9.2
Updates:
- FIX: Red Dashed Margins now stick correctly to the paper (Fixed coordinate mapping).
- RETAINED: All previous features (Panning, Dark Mode, Printing, etc).
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import datetime
import traceback
import math
from dataclasses import dataclass, asdict, replace
from typing import List, Optional, Tuple

from PIL import Image
import qrcode

from PySide6 import QtCore, QtGui, QtWidgets

# --- Optional libs ------------------------------------------------------------
_ESC_POS_AVAILABLE = True
try:
    from escpos.printer import Network, Serial, Usb
except ImportError:
    _ESC_POS_AVAILABLE = False
    print("WARNING: python-escpos not installed. Printing will be simulated.")

_BARCODE_AVAILABLE = True
try:
    import barcode
    from barcode.writer import ImageWriter
except Exception:
    _BARCODE_AVAILABLE = False

_PDF417_AVAILABLE = True
try:
    import pdf417gen
except Exception:
    _PDF417_AVAILABLE = False

# --- Constants ----------------------------------------------------------------
ORG_NAME = "MyReceiptApp"
APP_NAME = "ReceiptDesignerPro_v4"
DPI = 203  # Standard Thermal Printer DPI
PX_PER_MM = DPI / 25.4  # ~7.99 px per mm

# --- Threading Infrastructure -------------------------------------------------
class WorkerSignals(QtCore.QObject):
    finished = QtCore.Signal(bool, str)

class PrinterWorker(QtCore.QRunnable):
    def __init__(self, backend_config, action="print", image=None, cut=False, cut_mode="FULL", darkness=128):
        super().__init__()
        self.cfg = backend_config
        self.image = image
        self.cut_after = cut
        self.cut_mode = cut_mode
        self.darkness = darkness
        self.action = action
        self.signals = WorkerSignals()

    def run(self):
        printer = None
        try:
            printer = self._get_printer()
            if not printer:
                raise Exception("Could not initialize printer backend.")

            if self.action == "print":
                if self.image:
                    target_width = int(self.cfg.get('width_px', 512))
                    
                    if self.image.width != target_width:
                        w_percent = (target_width / float(self.image.width))
                        h_size = int((float(self.image.height) * float(w_percent)))
                        img_gray = self.image.convert('L')
                        img_resized = img_gray.resize((target_width, h_size), Image.Resampling.LANCZOS)
                        threshold = self.darkness 
                        self.image = img_resized.point(lambda p: 255 if p > threshold else 0).convert('1')
                    else:
                        self.image = self.image.convert('L').point(lambda p: 255 if p > self.darkness else 0).convert('1')

                    if hasattr(printer, "profile") and hasattr(printer.profile, "media"):
                        media = printer.profile.media
                        if isinstance(media, dict):
                            media['width']['pixels'] = target_width
                        elif hasattr(media, 'width') and hasattr(media.width, 'pixels'):
                             media.width.pixels = target_width

                    printer.image(self.image, impl="bitImageRaster", center=True)
                
                if self.cut_after:
                    printer.cut(mode=self.cut_mode)
                self.signals.finished.emit(True, "Printed successfully.")

            elif self.action == "feed":
                printer.text("\n\n\n")
                self.signals.finished.emit(True, "Fed paper.")

            elif self.action == "cut":
                printer.cut(mode=self.cut_mode)
                self.signals.finished.emit(True, f"{self.cut_mode} Cut performed.")
            
            if hasattr(printer, 'close'):
                printer.close()

        except Exception as e:
            traceback.print_exc()
            self.signals.finished.emit(False, f"Error: {str(e)}")
        finally:
            if printer and hasattr(printer, 'close'):
                try: printer.close()
                except: pass

    def _get_printer(self):
        if not _ESC_POS_AVAILABLE:
            raise Exception("python-escpos library is missing. Run: pip install python-escpos")
        
        DEFAULT_PROFILE = "TM-T88IV"
        t = self.cfg.get('type')
        if t == 'network':
            return Network(self.cfg.get('host'), int(self.cfg.get('port')), profile=DEFAULT_PROFILE)
        elif t == 'usb':
            return Usb(
                int(str(self.cfg.get('vid')), 16),
                int(str(self.cfg.get('pid')), 16),
                0,
                int(str(self.cfg.get('in')), 16),
                int(str(self.cfg.get('out')), 16),
                profile=DEFAULT_PROFILE
            )
        elif t == 'serial':
            return Serial(self.cfg.get('dev'), int(self.cfg.get('baud')), profile=DEFAULT_PROFILE)
        else:
            raise Exception("Unknown printer type.")

# --- Undo Infrastructure ------------------------------------------------------
class Command(QtGui.QUndoCommand): pass

class AddItemCmd(Command):
    def __init__(self, scene, item, text="Add"):
        super().__init__(text); self.scene = scene; self.item = item
    def undo(self): self.scene.removeItem(self.item)
    def redo(self):
        try:
            if self.item.scene() is None: self.scene.addItem(self.item)
            elif self.item.scene() is not self.scene:
                try: self.item.scene().removeItem(self.item)
                except: pass
                self.scene.addItem(self.item)
        except:
            try: self.scene.addItem(self.item)
            except: pass

class DeleteItemCmd(Command):
    def __init__(self, scene, item, text="Delete"):
        super().__init__(text); self.scene = scene; self.item = item; self.pos = item.pos(); 
        self.state = item.line() if isinstance(item, QtWidgets.QGraphicsLineItem) else (item.rect() if hasattr(item, 'rect') else None)
    def undo(self):
        self.scene.addItem(self.item); self.item.setPos(self.pos)
        if isinstance(self.item, QtWidgets.QGraphicsLineItem): self.item.setLine(self.state)
        elif hasattr(self.item, 'setRect') and self.state: self.item.setRect(self.state)
    def redo(self): self.scene.removeItem(self.item)

class MoveResizeCmd(Command):
    def __init__(self, item, old_pos, old_geom, new_pos, new_geom, text="Move/Resize"):
        super().__init__(text); self.item=item
        self.old_pos=old_pos; self.old_geom=old_geom
        self.new_pos=new_pos; self.new_geom=new_geom
        self.is_line = isinstance(item, QtWidgets.QGraphicsLineItem)
    def undo(self):
        self.item.setPos(self.old_pos)
        if self.old_geom is not None:
            if self.is_line: self.item.setLine(self.old_geom)
            elif hasattr(self.item, 'setRect'): self.item.setRect(self.old_geom)
    def redo(self):
        self.item.setPos(self.new_pos)
        if self.new_geom is not None:
            if self.is_line: self.item.setLine(self.new_geom)
            elif hasattr(self.item, 'setRect'): self.item.setRect(self.new_geom)

class PropertyChangeCmd(Command):
    def __init__(self, item, apply_fn, undo_fn, text="Change Property"):
        super().__init__(text); self.item=item; self.apply_fn=apply_fn; self.undo_fn=undo_fn
    def undo(self): self.undo_fn()
    def redo(self): self.apply_fn()

# --- Model -------------------------------------------------------------------
@dataclass
class Element:
    kind: str
    x: float; y: float; w: float; h: float
    text: str = ""; font_family: str = "Arial"; font_point: int = 12
    bold: bool = False; path: Optional[str] = None
    h_align: str = "left"; v_align: str = "top"; wrap_mode: str = "word"
    shrink_to_fit: bool = False; max_lines: int = 0; baseline_step: int = 0
    bc_type: str = "Code128"; bc_show_hrt: bool = True; bc_hrt_pos: str = "below"; bc_hrt_pt: int = 12
    shape_thickness: int = 2; shape_fill: bool = False
    x2: Optional[float] = None; y2: Optional[float] = None

@dataclass
class GuideGrid:
    x: float; y: float; w: float; h: float; rows: int = 3; cols: int = 2

@dataclass
class GuideLine:
    orientation: str; pos: float

@dataclass
class Template:
    paper_mm: int = 80; height_mm: int = 200; dpi: int = 203
    elements: List[Element] = None; guides: List[GuideGrid] = None; lines: List[GuideLine] = None
    def to_json(self) -> str:
        return json.dumps({
            "paper_mm": self.paper_mm, "height_mm": self.height_mm, "dpi": self.dpi,
            "elements": [asdict(e) for e in (self.elements or [])],
            "guides": [asdict(g) for g in (self.guides or [])],
            "lines": [asdict(l) for l in (self.lines or [])],
        }, indent=2)
    @staticmethod
    def from_json(s: str) -> "Template":
        d = json.loads(s)
        elems = [Element(**e) for e in d.get("elements", [])]
        guides = [GuideGrid(**g) for g in d.get("guides", [])]
        lines = [GuideLine(**l) for l in d.get("lines", [])]
        return Template(paper_mm=d.get("paper_mm", 80), height_mm=d.get("height_mm", 200), dpi=d.get("dpi", 203), elements=elems, guides=guides, lines=lines)

# --- Barcode/Image Logic ------------------------------------------------------
def ean13_checksum(data12: str) -> int:
    s = 0
    for i,ch in enumerate(data12): d=int(ch); s += d if i % 2 == 0 else 3*d
    return (10 - (s % 10)) % 10
def upca_checksum(data11: str) -> int:
    s=(sum(int(d) for d in data11[::2])*3)+sum(int(d) for d in data11[1::2])
    return (10 - (s % 10)) % 10

SUPPORTED_1D = ["Code128","Code39","EAN13","UPCA","ITF14"]

def render_barcode_to_qimage(kind: str, data: str, size: Tuple[int,int], show_hrt: bool, hrt_pos: str, hrt_pt: int) -> QtGui.QImage:
    w,h = size
    if kind == "PDF417" and _PDF417_AVAILABLE:
        try:
            codes = pdf417gen.encode(data, columns=6, security_level=2)
            im = pdf417gen.render_image(codes, scale=1, ratio=3, padding=2)
            im = im.convert('L').resize((w,h), resample=Image.NEAREST)
            buf = im.tobytes('raw','L')
            return QtGui.QImage(buf, w, h, w, QtGui.QImage.Format.Format_Grayscale8).copy()
        except: pass
    if not _BARCODE_AVAILABLE:
        img = QtGui.QImage(w,h, QtGui.QImage.Format.Format_Grayscale8); img.fill(255); return img

    if kind == "EAN13":
        digits = ''.join(ch for ch in data if ch.isdigit())
        if len(digits) == 12: data = digits + str(ean13_checksum(digits))
        elif len(digits) < 12: data = digits.ljust(12,'0') + str(ean13_checksum(digits.ljust(12,'0')))
    elif kind == "UPCA":
        digits = ''.join(ch for ch in data if ch.isdigit())
        if len(digits) == 11: data = digits + str(upca_checksum(digits))
        elif len(digits) < 11: data = digits.ljust(11,'0') + str(upca_checksum(digits.ljust(11,'0')))
    
    name_map = { "Code128":"code128", "Code39":"code39", "EAN13":"ean13", "UPCA":"upca", "ITF14":"itf14" }
    bc_name = name_map.get(kind, "code128")
    try:
        cls = barcode.get_barcode_class(bc_name); writer = ImageWriter()
        opts = { 'write_text': False, 'quiet_zone': 2.0, 'module_height': 10.0, 'module_width': 0.2 }
        pil_img = cls(data, writer=writer).render(writer_options=opts)
        final_img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_Grayscale8); final_img.fill(255)
        painter = QtGui.QPainter(final_img)
        try:
            bar_y, bar_h = 0, h
            text_rect_final = None
            if show_hrt:
                font = QtGui.QFont("Arial", max(6, int(hrt_pt))); painter.setFont(font)
                fm = QtGui.QFontMetrics(font)
                text_rect = fm.boundingRect(QtCore.QRect(0,0,w,h), QtCore.Qt.AlignCenter, data)
                text_h = text_rect.height() + 2 
                if text_h < h:
                    if hrt_pos == 'above': text_rect_final = QtCore.QRect(0, 0, w, text_h); bar_y = text_h; bar_h = h - text_h
                    else: bar_h = h - text_h; text_rect_final = QtCore.QRect(0, int(bar_h), w, text_h); bar_y = 0
            if bar_h > 2:
                pil_bars = pil_img.convert('L').resize((w, int(bar_h)), resample=Image.NEAREST)
                buf = pil_bars.tobytes('raw', 'L')
                q_bars = QtGui.QImage(buf, w, int(bar_h), w, QtGui.QImage.Format.Format_Grayscale8)
                painter.drawImage(0, int(bar_y), q_bars)
            if show_hrt and text_rect_final:
                painter.setPen(QtCore.Qt.black); painter.drawText(text_rect_final, QtCore.Qt.AlignCenter, data)
        finally: painter.end()
        return final_img
    except Exception:
        img = QtGui.QImage(w,h, QtGui.QImage.Format.Format_Grayscale8); img.fill(255); return img

def scene_to_image(scene: QtWidgets.QGraphicsScene, paper_px: int, height_px: int) -> Image.Image:
    """Renders the scene to a Python PIL Image (Monochrome compatible)."""
    qimg = QtGui.QImage(paper_px, height_px, QtGui.QImage.Format.Format_ARGB32)
    qimg.fill(QtCore.Qt.white)
    painter = QtGui.QPainter(qimg)
    target_rect = QtCore.QRectF(0, 0, paper_px, height_px)
    scene.render(painter, target=target_rect, source=target_rect)
    painter.end()
    ptr = qimg.constBits()
    try: raw_data = bytes(ptr)
    except: raw_data = ptr.tobytes()
    pil_img = Image.frombytes("RGBA", (paper_px, height_px), raw_data, "raw", "BGRA")
    return pil_img.convert('L').point(lambda x: 0 if x < 128 else 255, '1')

# --- Graphics Items -----------------------------------------------------------
class GLineItem(QtWidgets.QGraphicsLineItem):
    HANDLE_SZ = 10
    def __init__(self, elem: Element):
        super().__init__()
        self.elem = elem; self._locked = False; self._handle = None; self._resizing = False
        self.setPos(elem.x, elem.y)
        local_p2 = QtCore.QPointF(elem.x2 - elem.x, elem.y2 - elem.y) if elem.x2 is not None else QtCore.QPointF(elem.w, elem.h)
        self.setLine(QtCore.QLineF(0, 0, local_p2.x(), local_p2.y()))
        pen = QtGui.QPen(QtCore.Qt.black, elem.shape_thickness); pen.setCapStyle(QtCore.Qt.RoundCap); self.setPen(pen)
        self.setFlags(QtWidgets.QGraphicsItem.ItemIsMovable | QtWidgets.QGraphicsItem.ItemIsSelectable | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self._last_pos = self.pos(); self._last_line = self.line()
    def setLocked(self, locked: bool): self._locked = locked; self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, not locked)
    def boundingRect(self): r = super().boundingRect(); hs = self.HANDLE_SZ/2 + 2; return r.adjusted(-hs, -hs, hs, hs)
    def shape(self):
        path = QtGui.QPainterPath(); l = self.line(); stroker = QtGui.QPainterPathStroker(); stroker.setWidth(max(10, self.pen().width() + 4))
        path.addPath(stroker.createStroke(super().shape())); hs = self.HANDLE_SZ; path.addEllipse(l.p1(), hs, hs); path.addEllipse(l.p2(), hs, hs); return path
    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            l = self.line(); hs = self.HANDLE_SZ; painter.setPen(QtGui.QPen(QtCore.Qt.white, 1)); painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 120, 215)))
            painter.drawEllipse(l.p1(), hs/2, hs/2); painter.drawEllipse(l.p2(), hs/2, hs/2); painter.setPen(QtGui.QPen(QtGui.QColor(0, 120, 215), 1, QtCore.Qt.DashLine)); painter.setBrush(QtCore.Qt.NoBrush); painter.drawLine(l)
    def _get_handle_at(self, pos):
        hs = self.HANDLE_SZ; l = self.line()
        if QtCore.QLineF(pos, l.p1()).length() <= hs: return 'p1'
        if QtCore.QLineF(pos, l.p2()).length() <= hs: return 'p2'
        return None
    def hoverMoveEvent(self, event):
        if self._locked: return super().hoverMoveEvent(event)
        if self._get_handle_at(event.pos()): self.setCursor(QtCore.Qt.CrossCursor)
        else: self.setCursor(QtCore.Qt.ArrowCursor)
        super().hoverMoveEvent(event)
    def mousePressEvent(self, event):
        if self._locked: return super().mousePressEvent(event)
        if event.button() == QtCore.Qt.LeftButton:
            self._handle = self._get_handle_at(event.pos())
            if self._handle: self._resizing = True; self._last_pos = self.pos(); self._last_line = self.line(); event.accept(); return
        self._last_pos = self.pos(); self._last_line = self.line(); super().mousePressEvent(event)
    def mouseMoveEvent(self, event):
        if self._resizing:
            l = self.line(); new_pos = event.pos(); scn = self.scene()
            if scn and scn.property('snap'):
                grid = int(scn.property('grid') or 8); scene_pos = self.mapToScene(new_pos); snapped_scene = QtCore.QPointF(round(scene_pos.x()/grid)*grid, round(scene_pos.y()/grid)*grid); new_pos = self.mapFromScene(snapped_scene)
            if self._handle == 'p1': l.setP1(new_pos)
            elif self._handle == 'p2': l.setP2(new_pos)
            self.setLine(l); event.accept()
        else: super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False; self._handle = None; l = self.line()
            p1s, p2s = self.mapToScene(l.p1()), self.mapToScene(l.p2())
            self.elem.x, self.elem.y = p1s.x(), p1s.y(); self.elem.x2, self.elem.y2 = p2s.x(), p2s.y()
            self.elem.w, self.elem.h = self.elem.x2 - self.elem.x, self.elem.y2 - self.elem.y
            if self.pos() != self._last_pos or self.line() != self._last_line: self.scene().undo.push(MoveResizeCmd(self, self._last_pos, self._last_line, self.pos(), self.line()))
            event.accept(); return
        if self.pos() != self._last_pos:
             l = self.line(); p1s, p2s = self.mapToScene(l.p1()), self.mapToScene(l.p2())
             self.elem.x, self.elem.y = p1s.x(), p1s.y(); self.elem.x2, self.elem.y2 = p2s.x(), p2s.y()
             self.scene().undo.push(MoveResizeCmd(self, self._last_pos, self._last_line, self.pos(), self.line()))
        super().mouseReleaseEvent(event)
    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionChange and not self._resizing:
            scn = self.scene()
            if scn and scn.property('snap'): grid = int(scn.property('grid') or 8); return QtCore.QPointF(round(value.x()/grid)*grid, round(value.y()/grid)*grid)
        return super().itemChange(change, value)

class GItem(QtWidgets.QGraphicsRectItem):
    HANDLE_SZ = 14
    def __init__(self, elem: Element):
        super().__init__(0, 0, elem.w, elem.h)
        self.setFlags(QtWidgets.QGraphicsItem.ItemIsMovable | QtWidgets.QGraphicsItem.ItemIsSelectable | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges | QtWidgets.QGraphicsItem.ItemIsFocusable)
        self.setAcceptHoverEvents(True)
        self.elem = elem; self._resizing = False; self._handle = None; self._cache_qimage = None; self._cache_key = None; self._locked = False
        self._last_pos = QtCore.QPointF(elem.x, elem.y); self._last_rect = QtCore.QRectF(0,0,elem.w,elem.h)
    def setLocked(self, locked: bool): self._locked = locked; self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, not locked)
    def _resolve_text(self, text: str) -> str:
        if not text: return ""
        now = datetime.datetime.now()
        replacements = { "{{date}}": now.strftime("%Y-%m-%d"), "{{time}}": now.strftime("%H:%M"), "{{id}}": "TEST-001" }
        for k, v in replacements.items(): text = text.replace(k, v)
        return text
    def _ensure_cache(self):
        r = self.rect(); w = max(1, int(r.width())); h = max(1, int(r.height()))
        key = (self.elem.kind, self.elem.text, self.elem.path, w, h, self.elem.font_family, self.elem.font_point, 
               self.elem.bold, self.elem.h_align, self.elem.v_align, self.elem.wrap_mode, self.elem.shrink_to_fit, 
               self.elem.max_lines, self.elem.bc_type, self.elem.bc_show_hrt, self.elem.bc_hrt_pos, self.elem.bc_hrt_pt,
               self.elem.shape_thickness, self.elem.shape_fill)
        if key == self._cache_key and self._cache_qimage is not None: return
        img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_ARGB32); img.fill(QtCore.Qt.transparent); p = QtGui.QPainter(img)
        try:
            if self.elem.kind == 'text': self._paint_text(p, w, h)
            elif self.elem.kind == 'qr':
                try:
                    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=1, box_size=10)
                    qr.add_data(self._resolve_text(self.elem.text or ' ')); qr.make(fit=True)
                    pil = qr.make_image(fill_color="black", back_color="white").convert('L').resize((w, h))
                    p.drawImage(QtCore.QRectF(0, 0, w, h), QtGui.QImage(pil.tobytes('raw', 'L'), w, h, w, QtGui.QImage.Format.Format_Grayscale8))
                except: pass
            elif self.elem.kind == 'image' and self.elem.path:
                path = self.elem.path
                if not os.path.exists(path): path = os.path.join(os.getcwd(), os.path.basename(path))
                if os.path.exists(path): p.drawImage(QtCore.QRectF(0, 0, w, h), QtGui.QImage(path))
                else: p.drawText(QtCore.QRectF(0, 0, w, h), QtCore.Qt.AlignCenter, "Img Not Found")
            elif self.elem.kind == 'barcode':
                p.drawImage(QtCore.QRectF(0,0,w,h), render_barcode_to_qimage(self.elem.bc_type, self._resolve_text(self.elem.text), (w,h), self.elem.bc_show_hrt, self.elem.bc_hrt_pos, self.elem.bc_hrt_pt))
            elif self.elem.kind in ('rect', 'ellipse'):
                pen = QtGui.QPen(QtCore.Qt.black, self.elem.shape_thickness); p.setPen(pen)
                p.setBrush(QtCore.Qt.black if self.elem.shape_fill else QtCore.Qt.NoBrush)
                m = self.elem.shape_thickness / 2
                if self.elem.kind == 'rect': p.drawRect(QtCore.QRectF(m, m, w-m*2, h-m*2))
                else: p.drawEllipse(QtCore.QRectF(m, m, w-m*2, h-m*2))
        finally: p.end()
        self._cache_qimage = img; self._cache_key = key
    def _paint_text(self, p: QtGui.QPainter, w: int, h: int):
        size = int(self.elem.font_point); text = self._resolve_text(self.elem.text or "")
        f = QtGui.QFont(self.elem.font_family, size); f.setBold(self.elem.bold)
        flags = { "left": QtCore.Qt.AlignLeft, "center": QtCore.Qt.AlignHCenter, "right": QtCore.Qt.AlignRight }.get(self.elem.h_align, QtCore.Qt.AlignLeft) | \
                { "top": QtCore.Qt.AlignTop, "middle": QtCore.Qt.AlignVCenter, "bottom": QtCore.Qt.AlignBottom }.get(self.elem.v_align, QtCore.Qt.AlignTop)
        flags |= (QtCore.Qt.TextWordWrap if self.elem.wrap_mode == 'word' else QtCore.Qt.TextWrapAnywhere)
        if self.elem.shrink_to_fit and size > 5:
            min_pt, max_pt, final_pt = 4, size, size
            fm = QtGui.QFontMetrics(f); r = fm.boundingRect(QtCore.QRect(0,0,w,h*10), flags, text)
            if r.width() > w or r.height() > h:
                while min_pt <= max_pt:
                    mid_pt = (min_pt + max_pt) // 2
                    f.setPointSize(mid_pt); fm = QtGui.QFontMetrics(f); r = fm.boundingRect(QtCore.QRect(0,0,w,h*10), flags, text)
                    if r.width() <= w and r.height() <= h: final_pt = mid_pt; min_pt = mid_pt + 1
                    else: max_pt = mid_pt - 1
                f.setPointSize(max(4, final_pt))
        p.setFont(f); p.setPen(QtCore.Qt.black)
        if self.elem.max_lines > 0:
            layout = QtGui.QTextLayout(text, f); opt = QtGui.QTextOption(); opt.setWrapMode(QtGui.QTextOption.WordWrap if self.elem.wrap_mode=='word' else QtGui.QTextOption.WrapAnywhere)
            if self.elem.h_align == 'center': opt.setAlignment(QtCore.Qt.AlignHCenter)
            elif self.elem.h_align == 'right': opt.setAlignment(QtCore.Qt.AlignRight)
            layout.setTextOption(opt); layout.beginLayout()
            y=0; lines = []
            while True:
                line = layout.createLine()
                if not line.isValid(): break
                line.setLineWidth(w)
                if y + line.height() > h or (len(lines) >= self.elem.max_lines): break
                lines.append(line); y += line.height()
            layout.endLayout()
            for i, l in enumerate(lines): l.draw(p, QtCore.QPointF(0, i*l.height())) 
        else: p.drawText(QtCore.QRectF(0,0,w,h), flags, text)
    def boundingRect(self): return super().boundingRect().adjusted(-2, -2, 2, 2)
    def _handle_rect(self) -> QtCore.QRectF: return QtCore.QRectF(self.rect().right()-self.HANDLE_SZ, self.rect().bottom()-self.HANDLE_SZ, self.HANDLE_SZ, self.HANDLE_SZ)
    def paint(self, painter: QtGui.QPainter, option, widget=None):
        self._ensure_cache()
        if self._cache_qimage: painter.drawImage(self.rect(), self._cache_qimage)
        if self.isSelected():
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 120, 215), 1, QtCore.Qt.DashLine)); painter.drawRect(self.rect())
            painter.fillRect(self._handle_rect(), QtGui.QBrush(QtCore.Qt.black))
    def hoverMoveEvent(self, event):
        if self._locked: return super().hoverMoveEvent(event)
        if self._handle_rect().contains(event.pos()): self._handle = 'br'; self.setCursor(QtCore.Qt.SizeFDiagCursor)
        else: self._handle = None; self.setCursor(QtCore.Qt.ArrowCursor)
        super().hoverMoveEvent(event)
    def mousePressEvent(self, event):
        if self._locked: return super().mousePressEvent(event)
        if event.button() == QtCore.Qt.LeftButton and self._handle: self._resizing = True; event.accept(); return
        self._last_pos = self.pos(); self._last_rect = QtCore.QRectF(self.rect()); super().mousePressEvent(event)
    def mouseReleaseEvent(self, event):
        if self._locked: return super().mouseReleaseEvent(event)
        if self._resizing:
            self._resizing = False; r = self.rect()
            self.elem.w, self.elem.h = r.width(), r.height(); self.elem.x, self.elem.y = self.pos().x(), self.pos().y()
            self._cache_key = None; self.scene().undo.push(MoveResizeCmd(self, self._last_pos, self._last_rect, self.pos(), QtCore.QRectF(self.rect()))); event.accept(); return
        r = self.rect(); self.elem.w, self.elem.h = r.width(), r.height(); self.elem.x, self.elem.y = self.pos().x(), self.pos().y()
        if (self.pos() != self._last_pos) or (self.rect() != self._last_rect): self.scene().undo.push(MoveResizeCmd(self, self._last_pos, self._last_rect, self.pos(), QtCore.QRectF(self.rect())))
        super().mouseReleaseEvent(event)

    # --- MOUSE MOVE EVENT (Shift + QR Logic) ---
    def mouseMoveEvent(self, event):
        if self._locked: return super().mouseMoveEvent(event)
        if self._resizing:
            new_w = max(12, event.pos().x())
            new_h = max(12, event.pos().y())
            
            # 1. QR Code: Force Square
            if self.elem.kind == 'qr':
                side = max(new_w, new_h)
                new_w = side
                new_h = side
            
            # 2. Shift Key: Maintain Aspect Ratio
            elif (event.modifiers() & QtCore.Qt.ShiftModifier):
                orig_w = self._last_rect.width()
                orig_h = self._last_rect.height()
                if orig_h > 0:
                    aspect_ratio = orig_w / orig_h
                    new_h = new_w / aspect_ratio

            self.setRect(0, 0, new_w, new_h); self._cache_key = None; event.accept(); return
        super().mouseMoveEvent(event)
    
    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionChange:
            scn = self.scene(); new_pos = value
            if scn:
                x, y = new_pos.x(), new_pos.y()
                if scn.property('snap'): grid = int(scn.property('grid') or 8); x = round(x/grid)*grid; y = round(y/grid)*grid
                if self.elem.kind == 'text' and self.elem.baseline_step > 0: y = round(y/self.elem.baseline_step)*self.elem.baseline_step
                return QtCore.QPointF(x, y)
        return super().itemChange(change, value)

class GuideGridItem(QtWidgets.QGraphicsRectItem):
    HANDLE_SZ = 14
    def __init__(self, guide: GuideGrid):
        super().__init__(0, 0, guide.w, guide.h); self.guide = guide
        self.setFlags(QtWidgets.QGraphicsItem.ItemIsMovable | QtWidgets.QGraphicsItem.ItemIsSelectable | QtWidgets.QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True); self.setZValue(0.2); self._resizing = False; self._handle = None
        self._last_pos = QtCore.QPointF(guide.x, guide.y); self._last_rect = QtCore.QRectF(0,0,guide.w,guide.h)
    def _handle_rect(self) -> QtCore.QRectF: return QtCore.QRectF(self.rect().right()-self.HANDLE_SZ, self.rect().bottom()-self.HANDLE_SZ, self.HANDLE_SZ, self.HANDLE_SZ)
    def hoverMoveEvent(self, e):
        if self._handle_rect().contains(e.pos()): self.setCursor(QtCore.Qt.SizeFDiagCursor)
        else: self.setCursor(QtCore.Qt.ArrowCursor)
        super().hoverMoveEvent(e)
    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self._handle_rect().contains(e.pos()): self._resizing = True; e.accept(); self._last_pos = self.pos(); self._last_rect = QtCore.QRectF(self.rect())
        else: super().mousePressEvent(e)
    def mouseMoveEvent(self, e):
        if self._resizing: nw = max(24, e.pos().x()); nh = max(24, e.pos().y()); self.setRect(0, 0, nw, nh); e.accept()
        else: super().mouseMoveEvent(e)
    def mouseReleaseEvent(self, e):
        if self._resizing: self._resizing = False; r = self.rect(); self.guide.w, self.guide.h = r.width(), r.height(); e.accept()
        else: super().mouseReleaseEvent(e)
    def paint(self, painter: QtGui.QPainter, option, widget=None):
        if self.scene() and self.scene().property('printing'): return
        r = self.rect(); painter.setPen(QtGui.QPen(QtGui.QColor(180, 180, 180), 1, QtCore.Qt.DashLine)); painter.drawRect(r)
        rows, cols = max(1, self.guide.rows), max(1, self.guide.cols); painter.setPen(QtGui.QPen(QtGui.QColor(210, 210, 210), 1, QtCore.Qt.SolidLine))
        for c in range(1, cols): x = r.left() + c * (r.width()/cols); painter.drawLine(x, r.top(), x, r.bottom())
        for rr in range(1, rows): y = r.top() + rr * (r.height()/rows); painter.drawLine(r.left(), y, r.right(), y)
        if self.isSelected(): painter.fillRect(self._handle_rect(), QtGui.QBrush(QtCore.Qt.black))
    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionChange:
            scn = self.scene()
            if scn and scn.property('snap'): grid = int(scn.property('grid') or 8); return QtCore.QPointF(round(value.x()/grid)*grid, round(value.y()/grid)*grid)
        return super().itemChange(change, value)

class GuideLineItem(QtWidgets.QGraphicsLineItem):
    def __init__(self, orientation: str, pos: float, length: float):
        super().__init__(QtCore.QLineF(pos, 0, pos, length) if orientation == 'v' else QtCore.QLineF(0, pos, length, pos))
        self.orientation = orientation; self.setPen(QtGui.QPen(QtGui.QColor(140, 200, 255), 1, QtCore.Qt.SolidLine))
        self.setZValue(0.3); self.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, True); self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)
    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self.scene():
            vgs = [it.line().x1() for it in self.scene.items() if isinstance(it, GuideLineItem) and it.orientation=='v']
            hgs = [it.line().y1() for it in self.scene.items() if isinstance(it, GuideLineItem) and it.orientation=='h']
            self.scene().setProperty('vguides', sorted(vgs)); self.scene().setProperty('hguides', sorted(hgs))

# --- Ruler View (MODIFIED: Clean look, Fixed Margins & Signals) ---
class RulerView(QtWidgets.QGraphicsView):
    # Required for MainWin connection logic
    addVGuide = QtCore.Signal(float)
    addHGuide = QtCore.Signal(float)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw); self.setMouseTracking(True)
        self._panning = False
        self._pan_start = QtCore.QPoint()
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)

    def drawForeground(self, painter: QtGui.QPainter, rect: QtCore.QRectF):
        super().drawForeground(painter, rect)
        
        # 1. Get Paper Dimensions from Scene
        scene = self.scene()
        if not scene: return
        w = scene.property('paper_width')
        h = scene.property('paper_height')
        if not w or not h: return

        # 2. Calculate Printable Margin
        margin_mm = 5 if w < 500 else 4
        margin_px = margin_mm * PX_PER_MM

        # 3. Draw Red Dashed Margin Lines
        pen = QtGui.QPen(QtGui.QColor(255, 0, 0, 150)) # Red, semi-transparent
        pen.setStyle(QtCore.Qt.DashLine)
        pen.setWidth(2)
        painter.setPen(pen)

        # FIXED COORDINATES: Draw line directly on scene coordinates
        # Left Margin (at x = margin_px)
        painter.drawLine(margin_px, 0, margin_px, h)

        # Right Margin (at x = width - margin_px)
        painter.drawLine(w - margin_px, 0, w - margin_px, h)

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.MiddleButton:
            self._panning = True
            self._pan_start = e.position().toPoint()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        if self._panning:
            curr_pos = e.position().toPoint()
            delta = curr_pos - self._pan_start
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._pan_start = curr_pos
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):
        if self._panning:
            self._panning = False
            self.setCursor(QtCore.Qt.ArrowCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

# --- Layer Management ---------------------------------------------------------
class LayerList(QtWidgets.QListWidget):
    def __init__(self, scene, parent=None):
        super().__init__(parent); self.scene = scene
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.itemChanged.connect(self._on_item_changed)
        self.itemSelectionChanged.connect(self._on_list_selection)
        self.model().rowsMoved.connect(self._on_rows_moved)
        self._updating = False
    def refresh(self):
        if self._updating: return
        self._updating = True; self.clear()
        items = [i for i in self.scene.items() if isinstance(i, (GItem, GLineItem))]
        items.sort(key=lambda x: x.zValue(), reverse=True)
        for it in items:
            name = it.elem.kind.capitalize()
            if it.elem.kind == 'text': name += f": {it.elem.text[:15]}..."
            elif it.elem.kind == 'barcode': name += f": {it.elem.text}"
            elif it.elem.path: name += f": {os.path.basename(it.elem.path)}"
            li = QtWidgets.QListWidgetItem(name)
            li.setFlags(li.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsDragEnabled)
            li.setCheckState(QtCore.Qt.Checked if it.isVisible() else QtCore.Qt.Unchecked)
            li.setData(QtCore.Qt.UserRole, it)
            self.addItem(li)
            if it.isSelected(): li.setSelected(True)
        self._updating = False
    def _on_item_changed(self, item):
        if self._updating: return
        gitem = item.data(QtCore.Qt.UserRole)
        if gitem: gitem.setVisible(item.checkState() == QtCore.Qt.Checked)
    def _on_rows_moved(self, parent, start, end, dest, row):
        count = self.count()
        for i in range(count):
            li = self.item(i); gitem = li.data(QtCore.Qt.UserRole)
            if gitem: gitem.setZValue(count - i)
        self.scene.update()
    def _on_list_selection(self):
        if self._updating: return
        self._updating = True; self.scene.clearSelection()
        for i in range(self.count()):
            li = self.item(i); gitem = li.data(QtCore.Qt.UserRole)
            if gitem and li.isSelected(): gitem.setSelected(True)
        self._updating = False

# --- Main Window --------------------------------------------------------------
class MainWin(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Receipt Designer & Printer — Pro MVP v4.9.2")
        self.resize(1300, 900)
        self.settings = QtCore.QSettings(ORG_NAME, APP_NAME)
        self.template = Template(elements=[], guides=[], lines=[])
        self.threadpool = QtCore.QThreadPool.globalInstance()
        self.printer_cfg = self.load_printer_settings()
        self.setup_ui()
        self.update_paper()
        self.apply_theme()
        self.statusBar().showMessage("Ready. Loaded saved printer settings.")

    def load_printer_settings(self):
        t = self.settings.value("printer/type", "network")
        cfg = {"type": t, "width_px": int(self.settings.value("printer/width_px", 512))}
        if t == "network":
            cfg["host"] = self.settings.value("printer/net_host", "192.168.1.100")
            cfg["port"] = self.settings.value("printer/net_port", 9100)
        elif t == "usb":
            cfg["vid"] = self.settings.value("printer/usb_vid", "0x04b8")
            cfg["pid"] = self.settings.value("printer/usb_pid", "0x0202")
            cfg["in"] = self.settings.value("printer/usb_in", "0x82")
            cfg["out"] = self.settings.value("printer/usb_out", "0x01")
        elif t == "serial":
            cfg["dev"] = self.settings.value("printer/ser_dev", "/dev/ttyUSB0")
            cfg["baud"] = self.settings.value("printer/ser_baud", 9600)
        return cfg

    def setup_ui(self):
        self.scene = QtWidgets.QGraphicsScene(); self.scene.undo = QtGui.QUndoStack(self)
        self.view = RulerView(self.scene)
        self.view.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setCentralWidget(self.view)

        top_bar = QtWidgets.QToolBar("Main"); self.addToolBar(top_bar)
        top_bar.setIconSize(QtCore.QSize(16, 16))
        act_save = QtGui.QAction("💾 Save", self); act_save.triggered.connect(self.save_template); top_bar.addAction(act_save)
        act_load = QtGui.QAction("📂 Load", self); act_load.triggered.connect(self.load_template); top_bar.addAction(act_load)
        top_bar.addSeparator()
        
        act_print = QtGui.QAction("🖨️ Print", self); act_print.triggered.connect(self.print_now); top_bar.addAction(act_print)
        act_conf = QtGui.QAction("⚙️ Config", self); act_conf.triggered.connect(self.configure_printer); top_bar.addAction(act_conf)
        
        top_bar.addSeparator()
        act_feed = QtGui.QAction("▲ Feed", self); act_feed.triggered.connect(lambda: self.quick_action("feed")); top_bar.addAction(act_feed)
        act_cut = QtGui.QAction("✂ Cut", self); act_cut.triggered.connect(lambda: self.quick_action("cut")); top_bar.addAction(act_cut)
        top_bar.addSeparator()
        act_undo = self.scene.undo.createUndoAction(self, "Undo"); act_undo.setShortcut("Ctrl+Z"); top_bar.addAction(act_undo)
        act_redo = self.scene.undo.createRedoAction(self, "Redo"); act_redo.setShortcut("Ctrl+Y"); top_bar.addAction(act_redo)
        top_bar.addSeparator()

        self.paper_combo = QtWidgets.QComboBox(); self.paper_combo.addItems(["58 mm", "80 mm"]); self.paper_combo.setCurrentIndex(1)
        self.paper_combo.currentIndexChanged.connect(self.update_paper)
        lbl = QtWidgets.QLabel(" Width: "); top_bar.addWidget(lbl); top_bar.addWidget(self.paper_combo)
        self.paper_height = QtWidgets.QSpinBox(); self.paper_height.setRange(50, 5000); self.paper_height.setValue(200); self.paper_height.setSuffix(" mm")
        self.paper_height.valueChanged.connect(self.update_paper)
        lbl2 = QtWidgets.QLabel(" Height: "); top_bar.addWidget(lbl2); top_bar.addWidget(self.paper_height)

        self.cut_combo = QtWidgets.QComboBox()
        self.cut_combo.addItems(["Full Cut", "Partial Cut"])
        saved_cut = self.settings.value("printer/cut_mode", "Full Cut")
        self.cut_combo.setCurrentText(saved_cut)
        self.cut_combo.currentTextChanged.connect(lambda t: self.settings.setValue("printer/cut_mode", t))
        top_bar.addSeparator()
        top_bar.addWidget(QtWidgets.QLabel("  Cut: ")); top_bar.addWidget(self.cut_combo)

        self.darkness_spin = QtWidgets.QSpinBox(); self.darkness_spin.setRange(0, 255)
        saved_dark = int(self.settings.value("printer/darkness", 128))
        self.darkness_spin.setValue(saved_dark)
        self.darkness_spin.setToolTip("Higher = Darker/Bolder. Lower = Lighter/Finer.")
        self.darkness_spin.valueChanged.connect(lambda v: self.settings.setValue("printer/darkness", v))
        top_bar.addSeparator()
        top_bar.addWidget(QtWidgets.QLabel("  Darkness: ")); top_bar.addWidget(self.darkness_spin)

        menubar = self.menuBar()
        view_menu = menubar.addMenu("View")
        self.act_dark = QtGui.QAction("Dark Mode", self, checkable=True)
        self.act_dark.setChecked(str(self.settings.value("ui/dark_mode", "false")).lower() == 'true')
        self.act_dark.toggled.connect(self.toggle_theme)
        view_menu.addAction(self.act_dark)

        left_dock = QtWidgets.QDockWidget("Toolbox", self); self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, left_dock)
        left_tabs = QtWidgets.QTabWidget(); left_dock.setWidget(left_tabs)

        tab_insert = QtWidgets.QWidget(); lay_ins = QtWidgets.QVBoxLayout(tab_insert)
        b_text = QtWidgets.QPushButton("📝 Text"); b_text.clicked.connect(self.add_text); lay_ins.addWidget(b_text)
        b_qr = QtWidgets.QPushButton("🏁 QR Code"); b_qr.clicked.connect(self.add_qr); lay_ins.addWidget(b_qr)
        b_bc = QtWidgets.QPushButton("║▌ Barcode"); b_bc.clicked.connect(self.add_barcode); lay_ins.addWidget(b_bc)
        b_img = QtWidgets.QPushButton("🖼️ Image"); b_img.clicked.connect(self.add_image); lay_ins.addWidget(b_img)
        lay_ins.addSpacing(10)
        lay_ins.addWidget(QtWidgets.QLabel("<b>Shapes</b>"))
        b_line = QtWidgets.QPushButton("／ Line"); b_line.clicked.connect(lambda: self.add_shape('line')); lay_ins.addWidget(b_line)
        b_rect = QtWidgets.QPushButton("☐ Rect"); b_rect.clicked.connect(lambda: self.add_shape('rect')); lay_ins.addWidget(b_rect)
        b_circ = QtWidgets.QPushButton("◯ Circle"); b_circ.clicked.connect(lambda: self.add_shape('ellipse')); lay_ins.addWidget(b_circ)
        lay_ins.addSpacing(10)
        b_tbl = QtWidgets.QPushButton("▦ Layout Table"); b_tbl.clicked.connect(self.add_layout_table); lay_ins.addWidget(b_tbl)
        b_fit = QtWidgets.QPushButton("Fit to Cell"); b_fit.clicked.connect(self.fit_selected_to_cell); lay_ins.addWidget(b_fit)
        lay_ins.addStretch()
        left_tabs.addTab(tab_insert, "Insert")

        tab_arr = QtWidgets.QWidget(); lay_arr = QtWidgets.QVBoxLayout(tab_arr)
        lay_arr.addWidget(QtWidgets.QLabel("<b>Align Page</b>"))
        h_lay = QtWidgets.QHBoxLayout(); b_al = QtWidgets.QPushButton("Left"); b_ac = QtWidgets.QPushButton("Center"); b_ar = QtWidgets.QPushButton("Right")
        for b, w in zip((b_al, b_ac, b_ar), ('left', 'hcenter', 'right')): b.clicked.connect(lambda _,w=w: self.align_selected(w)); h_lay.addWidget(b)
        lay_arr.addLayout(h_lay)
        v_lay = QtWidgets.QHBoxLayout(); b_at = QtWidgets.QPushButton("Top"); b_vc = QtWidgets.QPushButton("Mid"); b_ab = QtWidgets.QPushButton("Bot")
        for b, w in zip((b_at, b_vc, b_ab), ('top', 'vcenter', 'bottom')): b.clicked.connect(lambda _,w=w: self.align_selected(w)); v_lay.addWidget(b)
        lay_arr.addLayout(v_lay)
        lay_arr.addWidget(QtWidgets.QLabel("<b>Distribute</b>"))
        b_dh = QtWidgets.QPushButton("Distribute Horiz"); b_dh.clicked.connect(lambda: self.distribute_selected('h')); lay_arr.addWidget(b_dh)
        b_dv = QtWidgets.QPushButton("Distribute Vert"); b_dv.clicked.connect(lambda: self.distribute_selected('v')); lay_arr.addWidget(b_dv)
        lay_arr.addSpacing(10)
        b_front = QtWidgets.QPushButton("Bring Front"); b_front.clicked.connect(self.bring_front); lay_arr.addWidget(b_front)
        b_back = QtWidgets.QPushButton("Send Back"); b_back.clicked.connect(self.send_back); lay_arr.addWidget(b_back)
        b_grp = QtWidgets.QPushButton("Group"); b_grp.clicked.connect(self.group_selected); lay_arr.addWidget(b_grp)
        b_ungrp = QtWidgets.QPushButton("Ungroup"); b_ungrp.clicked.connect(self.ungroup_selected); lay_arr.addWidget(b_ungrp)
        b_lock = QtWidgets.QPushButton("Lock/Unlock"); b_lock.clicked.connect(self.toggle_lock); lay_arr.addWidget(b_lock)
        lay_arr.addStretch()
        left_tabs.addTab(tab_arr, "Arrange")

        tab_grid = QtWidgets.QWidget(); lay_grid = QtWidgets.QVBoxLayout(tab_grid)
        self.snap_check = QtWidgets.QCheckBox("Snap to Grid"); self.snap_check.setChecked(True)
        self.snap_check.toggled.connect(self.update_grid_settings); lay_grid.addWidget(self.snap_check)
        lay_g2 = QtWidgets.QHBoxLayout(); lay_g2.addWidget(QtWidgets.QLabel("Px:")); self.grid_spin = QtWidgets.QSpinBox(); self.grid_spin.setRange(2, 64); self.grid_spin.setValue(8); lay_g2.addWidget(self.grid_spin)
        self.grid_spin.valueChanged.connect(self.update_grid_settings); lay_grid.addLayout(lay_g2)
        lay_grid.addSpacing(10)
        self.snap_guides = QtWidgets.QCheckBox("Snap to Guides"); self.snap_guides.setChecked(True)
        self.snap_guides.toggled.connect(lambda v: self.scene.setProperty('snap_guides', bool(v))); lay_grid.addWidget(self.snap_guides)
        b_clr = QtWidgets.QPushButton("Clear Guides"); b_clr.clicked.connect(self.clear_guides); lay_grid.addWidget(b_clr)
        lay_grid.addStretch()
        left_tabs.addTab(tab_grid, "Grid")
        
        self.layer_list = LayerList(self.scene)
        left_tabs.addTab(self.layer_list, "Layers")
        self.scene.selectionChanged.connect(lambda: self.layer_list.refresh() if not self.layer_list._updating else None)

        right_dock = QtWidgets.QDockWidget("Properties", self); self.addDockWidget(QtCore.Qt.RightDockWidgetArea, right_dock)
        prop_widget = QtWidgets.QWidget(); right_dock.setWidget(prop_widget)
        form = QtWidgets.QFormLayout(prop_widget); form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        self.prop_text = QtWidgets.QPlainTextEdit(); self.prop_text.setMaximumHeight(60)
        self.prop_font = QtWidgets.QFontComboBox(); self.prop_font.setCurrentFont(QtGui.QFont("Arial"))
        self.prop_size = QtWidgets.QSpinBox(); self.prop_size.setRange(6, 72); self.prop_size.setValue(12)
        self.prop_bold = QtWidgets.QCheckBox("Bold")
        self.prop_align_h = QtWidgets.QComboBox(); self.prop_align_h.addItems(["left","center","right"])
        self.prop_align_v = QtWidgets.QComboBox(); self.prop_align_v.addItems(["top","middle","bottom"])
        self.prop_wrap = QtWidgets.QComboBox(); self.prop_wrap.addItems(["word","anywhere"])
        self.prop_shrink = QtWidgets.QCheckBox("Shrink to fit")
        self.prop_maxlines = QtWidgets.QSpinBox(); self.prop_maxlines.setRange(0, 20)
        self.prop_baseline = QtWidgets.QSpinBox(); self.prop_baseline.setRange(0, 64)
        self.prop_path = QtWidgets.QLineEdit(); self.prop_path.setPlaceholderText("Image path…")
        self.prop_bc_type = QtWidgets.QComboBox(); self.prop_bc_type.addItems(SUPPORTED_1D + (["PDF417"] if _PDF417_AVAILABLE else []))
        self.prop_bc_hrt = QtWidgets.QCheckBox("Show HRT"); self.prop_bc_hrt.setChecked(True)
        self.prop_bc_pos = QtWidgets.QComboBox(); self.prop_bc_pos.addItems(["below","above"])
        self.prop_bc_pt = QtWidgets.QSpinBox(); self.prop_bc_pt.setRange(6, 48); self.prop_bc_pt.setValue(12)
        self.prop_shape_thick = QtWidgets.QSpinBox(); self.prop_shape_thick.setRange(1, 50); self.prop_shape_thick.setValue(2)
        self.prop_shape_fill = QtWidgets.QCheckBox("Fill (Black)")
        self.prop_rows = QtWidgets.QSpinBox(); self.prop_rows.setRange(1, 50); self.prop_rows.setValue(3)
        self.prop_cols = QtWidgets.QSpinBox(); self.prop_cols.setRange(1, 50); self.prop_cols.setValue(2)

        form.addRow(QtWidgets.QLabel("<b>Element Props</b>"))
        form.addRow("Data:", self.prop_text)
        form.addRow("Font:", self.prop_font)
        form.addRow("Size:", self.prop_size)
        form.addRow("", self.prop_bold)
        form.addRow("H-Align:", self.prop_align_h)
        form.addRow("V-Align:", self.prop_align_v)
        form.addRow("Wrap:", self.prop_wrap)
        form.addRow("", self.prop_shrink)
        form.addRow("Max Lines:", self.prop_maxlines)
        form.addRow("Baseline:", self.prop_baseline)
        form.addRow("Img Path:", self.prop_path)
        form.addRow(QtWidgets.QLabel("<b>Shape Props</b>"))
        form.addRow("Thickness:", self.prop_shape_thick)
        form.addRow("", self.prop_shape_fill)
        form.addRow(QtWidgets.QLabel("<b>Barcode</b>"))
        form.addRow("Type:", self.prop_bc_type)
        form.addRow("", self.prop_bc_hrt)
        form.addRow("HRT Pos:", self.prop_bc_pos)
        form.addRow("HRT Size:", self.prop_bc_pt)
        form.addRow(QtWidgets.QLabel("<b>Grid Props</b>"))
        form.addRow("Rows:", self.prop_rows)
        form.addRow("Cols:", self.prop_cols)

        self.scene.selectionChanged.connect(self.update_properties_from_selection)
        all_props = (self.prop_text, self.prop_font, self.prop_size, self.prop_bold, self.prop_align_h, self.prop_align_v,
                     self.prop_wrap, self.prop_shrink, self.prop_maxlines, self.prop_baseline, self.prop_path,
                     self.prop_bc_type, self.prop_bc_hrt, self.prop_bc_pos, self.prop_bc_pt,
                     self.prop_shape_thick, self.prop_shape_fill, self.prop_rows, self.prop_cols)
        for w in all_props:
            if hasattr(w, 'textChanged'): w.textChanged.connect(self.apply_properties)
            elif hasattr(w, 'currentTextChanged'): w.currentTextChanged.connect(self.apply_properties)
            elif hasattr(w, 'valueChanged'): w.valueChanged.connect(self.apply_properties)
            elif hasattr(w, 'toggled'): w.toggled.connect(self.apply_properties)
        
        self.view.addVGuide.connect(self.add_vguide_from_view)
        self.view.addHGuide.connect(self.add_hguide_from_view)
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Delete), self, self.delete_selected)
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Backspace), self, self.delete_selected)

    def toggle_theme(self, checked):
        self.settings.setValue("ui/dark_mode", checked)
        self.apply_theme()
    
    def apply_theme(self):
        dark_mode = str(self.settings.value("ui/dark_mode", "false")).lower() == 'true'
        app = QtWidgets.QApplication.instance()
        if dark_mode:
            palette = QtGui.QPalette()
            palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
            palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.Base, QtGui.QColor(25, 25, 25))
            palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
            palette.setColor(QtGui.QPalette.ToolTipBase, QtCore.Qt.black)
            palette.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
            palette.setColor(QtGui.QPalette.ButtonText, QtCore.Qt.white)
            palette.setColor(QtGui.QPalette.BrightText, QtCore.Qt.red)
            palette.setColor(QtGui.QPalette.Link, QtGui.QColor(42, 130, 218))
            palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
            palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
            app.setPalette(palette)
            self.view.setBackgroundBrush(QtGui.QColor(80, 80, 80))
            if hasattr(self, 'paper_item') and self.paper_item: 
                self.paper_item.setBrush(QtGui.QBrush(QtGui.QColor(240, 240, 240)))
        else:
            app.setPalette(QtGui.QPalette())
            self.view.setBackgroundBrush(QtGui.QColor(160, 160, 160))
            if hasattr(self, 'paper_item') and self.paper_item: 
                self.paper_item.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255)))
        self.view.viewport().update()

    def paper_px(self) -> int:
        mm = 58 if self.paper_combo.currentIndex() == 0 else 80
        return int((mm / 25.4) * self.template.dpi)

    def update_paper(self):
        self.template.height_mm = self.paper_height.value()
        px = self.paper_px()
        h_px = int((self.template.height_mm / 25.4) * self.template.dpi)
        
        self.scene.clear()
        self.paper_item = None
        
        # --- MARGIN LOGIC ---
        # Add 100px margin on all sides to allow scrolling past edge
        margin = 100
        self.scene.setSceneRect(-margin, -margin, px + (margin*2), h_px + (margin*2))
        self.scene.setProperty('paper_width', px)
        self.scene.setProperty('snap_guides', self.snap_guides.isChecked())
        
        # Draw Paper at 0,0
        paper = QtWidgets.QGraphicsRectItem(0, 0, px, h_px)
        paper.setPen(QtGui.QPen(QtGui.QColor(200, 200, 200))) # Light border
        paper.setZValue(-1)
        
        # --- SHADOW EFFECT ---
        shadow = QtWidgets.QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QtGui.QColor(0,0,0,80))
        shadow.setOffset(0,0)
        paper.setGraphicsEffect(shadow)
        
        self.scene.addItem(paper)
        self.paper_item = paper
        
        self.apply_theme() # Apply colors
        self.update_grid_settings()
        
        for g in (self.template.guides or []): self.scene.addItem(GuideGridItem(g)).setPos(g.x, g.y)
        for l in (self.template.lines or []): self._add_guide_line(l)
        for e in (self.template.elements or []):
             if e.kind == 'line': item = GLineItem(e)
             else: item = GItem(e)
             item.setZValue(1); self.scene.addItem(item); item.setPos(e.x, e.y)
        
        # Center view initially
        self.view.centerOn(px/2, h_px/2)
        self._reindex_guides()
        self.layer_list.refresh()

    def update_grid_settings(self):
        snap = self.snap_check.isChecked(); grid = self.grid_spin.value()
        self.scene.setProperty('snap', snap); self.scene.setProperty('grid', grid)

    def _push(self, it):
        cmd = AddItemCmd(self.scene, it); self.scene.undo.push(cmd); cmd.redo()
        self.layer_list.refresh()

    def add_text(self): 
        if self.template.elements is None: self.template.elements = []
        e=Element(kind='text',x=10,y=10,w=200,h=50,text="New Text"); self.template.elements.append(e)
        it=GItem(e); it.setPos(10,10); self._push(it); it.setSelected(True); self.view.ensureVisible(it)
    def add_qr(self): 
        if self.template.elements is None: self.template.elements = []
        e=Element(kind='qr',x=10,y=70,w=100,h=100,text="http://"); self.template.elements.append(e)
        it=GItem(e); it.setPos(10,70); self._push(it); it.setSelected(True); self.view.ensureVisible(it)
    def add_image(self):
        p,_ = QtWidgets.QFileDialog.getOpenFileName(self, "Img", "", "Images (*.png *.jpg *.bmp)")
        if not p: return
        target_w, target_h = 200.0, 150.0
        try:
            img = QtGui.QImage(p)
            if not img.isNull() and img.width() > 0: target_h = target_w * (img.height() / img.width())
        except: pass
        if self.template.elements is None: self.template.elements = []
        e=Element(kind='image',x=10,y=200,w=target_w,h=target_h,path=p)
        self.template.elements.append(e)
        it=GItem(e); it.setPos(10,200); self._push(it); it.setSelected(True); self.view.ensureVisible(it)
    def add_barcode(self): 
        if self.template.elements is None: self.template.elements = []
        e=Element(kind='barcode',x=10,y=350,w=200,h=80,text="123456"); self.template.elements.append(e)
        it=GItem(e); it.setPos(10,350); self._push(it); it.setSelected(True); self.view.ensureVisible(it)
    def add_shape(self, kind):
        if self.template.elements is None: self.template.elements = []
        if kind == 'line': e = Element(kind=kind, x=50, y=50, w=100, h=100, x2=150, y2=50, shape_thickness=2); self.template.elements.append(e); it = GLineItem(e); it.setPos(50, 50)
        else:
            w, h = 100, 50
            if kind == 'ellipse': h = 100
            e=Element(kind=kind, x=50, y=50, w=w, h=h); self.template.elements.append(e); it=GItem(e); it.setPos(50,50)
        self._push(it); it.setSelected(True); self.view.ensureVisible(it)
    def add_layout_table(self): 
        if self.template.guides is None: self.template.guides = []
        g=GuideGrid(0,50,self.paper_px(),200); self.template.guides.append(g); it=GuideGridItem(g); it.setPos(0,50); self.scene.addItem(it); it.setSelected(True)
    def fit_selected_to_cell(self):
        it = self.selected_item(); 
        if not it: return
        c = it.sceneBoundingRect().center()
        tables = [x for x in self.scene.items(c) if isinstance(x, GuideGridItem)]
        if not tables: return
        tbl = tables[0]; r = tbl.mapRectToScene(tbl.rect()); rows, cols = max(1,tbl.guide.rows), max(1,tbl.guide.cols)
        cw, ch = r.width()/cols, r.height()/rows
        col = max(0, min(cols-1, int((c.x()-r.left())/cw))); row = max(0, min(rows-1, int((c.y()-r.top())/ch)))
        nx, ny = r.left()+col*cw, r.top()+row*ch
        old_pos = it.pos(); old_geom = it.line() if isinstance(it, GLineItem) else QtCore.QRectF(it.rect())
        it.setPos(nx, ny)
        if isinstance(it, GLineItem): it.setLine(QtCore.QLineF(0, 0, cw, ch)); it.elem.x, it.elem.y = nx, ny; it.elem.x2, it.elem.y2 = nx+cw, ny+ch
        else: it.setRect(0,0,cw,ch); it.elem.x,it.elem.y,it.elem.w,it.elem.h = nx,ny,cw,ch
        new_geom = it.line() if isinstance(it, GLineItem) else QtCore.QRectF(it.rect())
        self.scene.undo.push(MoveResizeCmd(it, old_pos, old_geom, it.pos(), new_geom))
    def _add_guide_line(self, l: GuideLine):
        length = self.scene.height(); self.scene.addItem(GuideLineItem(l.orientation, l.pos, length)); self._reindex_guides()
    def add_vguide_from_view(self, x): 
        if self.template.lines is None: self.template.lines = []
        l=GuideLine('v', float(x)); self.template.lines.append(l); self._add_guide_line(l)
    def add_hguide_from_view(self, y): 
        if self.template.lines is None: self.template.lines = []
        l=GuideLine('h', float(y)); self.template.lines.append(l); self._add_guide_line(l)
    def clear_guides(self):
        self.template.lines = []; 
        for i in self.scene.items(): 
            if isinstance(i, GuideLineItem): self.scene.removeItem(i)
        self._reindex_guides()
    def _reindex_guides(self):
        self.scene.setProperty('vguides', sorted([i.line().x1() for i in self.scene.items() if isinstance(i, GuideLineItem) and i.orientation=='v']))
        self.scene.setProperty('hguides', sorted([i.line().y1() for i in self.scene.items() if isinstance(i, GuideLineItem) and i.orientation=='h']))

    def selected_item(self): sel = self.scene.selectedItems(); return sel[0] if sel else None

    def update_properties_from_selection(self):
        it = self.selected_item()
        all_widgets = (self.prop_text, self.prop_font, self.prop_size, self.prop_bold, 
                       self.prop_align_h, self.prop_align_v, self.prop_wrap, self.prop_shrink,
                       self.prop_maxlines, self.prop_baseline, self.prop_path, 
                       self.prop_bc_type, self.prop_bc_hrt, self.prop_bc_pos, self.prop_bc_pt,
                       self.prop_shape_thick, self.prop_shape_fill, self.prop_rows, self.prop_cols)
        for w in all_widgets: w.blockSignals(True)

        if not it:
            for w in all_widgets: w.setEnabled(False)
        elif isinstance(it, GuideGridItem):
            for w in all_widgets: w.setEnabled(False)
            self.prop_rows.setEnabled(True); self.prop_cols.setEnabled(True)
            self.prop_rows.setValue(it.guide.rows); self.prop_cols.setValue(it.guide.cols)
        elif isinstance(it, (GItem, GLineItem)):
            k = it.elem.kind
            is_text, is_bc, is_qr, is_img = k=='text', k=='barcode', k=='qr', k=='image'
            is_shape, is_line = k in ('rect', 'ellipse', 'line'), k=='line'
            self.prop_text.setEnabled(is_text or is_bc or is_qr)
            self.prop_font.setEnabled(is_text); self.prop_size.setEnabled(is_text)
            self.prop_bold.setEnabled(is_text); self.prop_align_h.setEnabled(is_text)
            self.prop_align_v.setEnabled(is_text); self.prop_wrap.setEnabled(is_text)
            self.prop_shrink.setEnabled(is_text); self.prop_maxlines.setEnabled(is_text)
            self.prop_baseline.setEnabled(is_text); self.prop_path.setEnabled(is_img)
            self.prop_bc_type.setEnabled(is_bc); self.prop_bc_hrt.setEnabled(is_bc)
            self.prop_bc_pos.setEnabled(is_bc); self.prop_bc_pt.setEnabled(is_bc)
            self.prop_shape_thick.setEnabled(is_shape); self.prop_shape_fill.setEnabled(is_shape and not is_line)
            self.prop_rows.setEnabled(False); self.prop_cols.setEnabled(False)
            self.prop_text.setPlainText(it.elem.text)
            self.prop_font.setCurrentFont(QtGui.QFont(it.elem.font_family))
            self.prop_size.setValue(it.elem.font_point)
            self.prop_bold.setChecked(it.elem.bold)
            self.prop_align_h.setCurrentText(it.elem.h_align)
            self.prop_align_v.setCurrentText(it.elem.v_align)
            self.prop_wrap.setCurrentText(it.elem.wrap_mode)
            self.prop_shrink.setChecked(it.elem.shrink_to_fit)
            self.prop_maxlines.setValue(it.elem.max_lines)
            self.prop_baseline.setValue(it.elem.baseline_step)
            self.prop_path.setText(it.elem.path or "")
            self.prop_bc_type.setCurrentText(it.elem.bc_type)
            self.prop_bc_hrt.setChecked(it.elem.bc_show_hrt)
            self.prop_bc_pos.setCurrentText(it.elem.bc_hrt_pos)
            self.prop_bc_pt.setValue(it.elem.bc_hrt_pt)
            self.prop_shape_thick.setValue(it.elem.shape_thickness)
            self.prop_shape_fill.setChecked(it.elem.shape_fill)
        for w in all_widgets: w.blockSignals(False)

    def apply_properties(self):
        it = self.selected_item()
        if not it: return
        if isinstance(it, (GItem, GLineItem)):
            old_e = replace(it.elem)
            it.elem.text = self.prop_text.toPlainText()
            it.elem.font_family = self.prop_font.currentFont().family()
            it.elem.font_point = self.prop_size.value()
            it.elem.bold = self.prop_bold.isChecked()
            it.elem.h_align = self.prop_align_h.currentText()
            it.elem.v_align = self.prop_align_v.currentText()
            it.elem.wrap_mode = self.prop_wrap.currentText()
            it.elem.shrink_to_fit = self.prop_shrink.isChecked()
            it.elem.max_lines = self.prop_maxlines.value()
            it.elem.baseline_step = self.prop_baseline.value()
            it.elem.path = self.prop_path.text() or None
            it.elem.bc_type = self.prop_bc_type.currentText()
            it.elem.bc_show_hrt = self.prop_bc_hrt.isChecked()
            it.elem.bc_hrt_pos = self.prop_bc_pos.currentText()
            it.elem.bc_hrt_pt = self.prop_bc_pt.value()
            it.elem.shape_thickness = self.prop_shape_thick.value()
            it.elem.shape_fill = self.prop_shape_fill.isChecked()
            if isinstance(it, GLineItem):
                pen = it.pen(); pen.setWidth(it.elem.shape_thickness); it.setPen(pen)
            else: it._cache_key = None; it.update()
            new_e = replace(it.elem)
            def undo(): 
                it.elem = replace(old_e)
                if isinstance(it, GLineItem): it.setPen(QtGui.QPen(QtCore.Qt.black, old_e.shape_thickness))
                else: it._cache_key=None; it.update()
            def redo(): 
                it.elem = replace(new_e)
                if isinstance(it, GLineItem): it.setPen(QtGui.QPen(QtCore.Qt.black, new_e.shape_thickness))
                else: it._cache_key=None; it.update()
            self.scene.undo.push(PropertyChangeCmd(it, redo, undo))
        elif isinstance(it, GuideGridItem):
            it.guide.rows = self.prop_rows.value(); it.guide.cols = self.prop_cols.value(); it.update() 

    def _sel(self): return [i for i in self.scene.selectedItems() if isinstance(i, (GItem, GLineItem, GuideGridItem))]
    def align_selected(self, w):
        sel = self._sel(); sr = self.scene.sceneRect()
        paper_w = self.scene.property('paper_width') or 400
        paper_h = self.paper_height.value() / 25.4 * 203 
        for i in sel:
            r=i.sceneBoundingRect(); x,y = i.pos().x(), i.pos().y()
            if w=='left': x=0
            elif w=='right': x=paper_w-r.width()
            elif w=='hcenter': x=(paper_w-r.width())/2
            elif w=='top': y=0
            elif w=='bottom': y=paper_h-r.height()
            elif w=='vcenter': y=(paper_h-r.height())/2
            old=i.pos(); i.setPos(x,y)
            if hasattr(i, 'elem'): i.elem.x, i.elem.y = x, y
            self.scene.undo.push(MoveResizeCmd(i, old, None, i.pos(), None))
    def distribute_selected(self, ax):
        items = sorted([i for i in self._sel() if isinstance(i, (GItem, GLineItem))], key=lambda x: x.pos().x() if ax=='h' else x.pos().y())
        if len(items)<3: return
        start = items[0].pos().x() if ax=='h' else items[0].pos().y()
        end = items[-1].pos().x() if ax=='h' else items[-1].pos().y()
        step = (end-start)/(len(items)-1)
        for idx, i in enumerate(items[1:-1], 1):
            old=i.pos(); val = start + step*idx
            if ax=='h': i.setPos(val, i.pos().y()); i.elem.x = val
            else: i.setPos(i.pos().x(), val); i.elem.y = val
            self.scene.undo.push(MoveResizeCmd(i, old, None, i.pos(), None))
    def bring_front(self): 
        for i in self._sel(): i.setZValue(i.zValue()+1)
        self.layer_list.refresh()
    def send_back(self): 
        for i in self._sel(): i.setZValue(i.zValue()-1)
        self.layer_list.refresh()
    def group_selected(self):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, (GItem, GLineItem))]
        if len(sel)>1: g=self.scene.createItemGroup(sel); g.setFlags(QtWidgets.QGraphicsItem.ItemIsMovable|QtWidgets.QGraphicsItem.ItemIsSelectable)
        self.layer_list.refresh()
    def ungroup_selected(self):
        for i in self.scene.selectedItems():
            if isinstance(i, QtWidgets.QGraphicsItemGroup): self.scene.destroyItemGroup(i)
        self.layer_list.refresh()
    def toggle_lock(self):
        for i in self._sel(): 
            if isinstance(i, (GItem, GLineItem)): i.setLocked(not i._locked)
    def delete_selected(self):
        for i in self.scene.selectedItems(): self.scene.undo.push(DeleteItemCmd(self.scene, i))
        self.layer_list.refresh()

    # --- Save/Load ---
    def save_template(self):
        p,_ = QtWidgets.QFileDialog.getSaveFileName(self, "Save", "template.json", "JSON (*.json)")
        if p: 
            with open(p,'w') as f: f.write(self.template.to_json())
    def load_template(self):
        p,_ = QtWidgets.QFileDialog.getOpenFileName(self, "Load", "", "JSON (*.json)")
        if p:
            with open(p,'r') as f: self.template = Template.from_json(f.read())
            self.paper_height.setValue(self.template.height_mm)
            self.update_paper()

    # --- PRINT ACTIONS ---
    def print_now(self):
        self.printer_cfg = self.load_printer_settings()
        if not self.printer_cfg.get('type'):
            self.configure_printer()
            if not self.settings.value("printer/type"): return

        px = self.paper_px(); br = self.scene.itemsBoundingRect(); h = int(max(br.bottom(), 600))
        self.scene.setProperty('printing', True)
        img = scene_to_image(self.scene, px, h)
        self.scene.setProperty('printing', False)
        
        cut_val = "PART" if "Partial" in self.cut_combo.currentText() else "FULL"
        dark_val = self.darkness_spin.value()
        
        self.statusBar().showMessage("Printing...")
        w = PrinterWorker(self.printer_cfg, action="print", image=img, cut=True, cut_mode=cut_val, darkness=dark_val)
        w.signals.finished.connect(self.on_print_finished)
        self.threadpool.start(w)

    def configure_printer(self):
        dlg = PrintDialog(self.settings, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.printer_cfg = self.load_printer_settings()
            self.statusBar().showMessage("Printer configuration saved.")

    def quick_action(self, action):
        self.printer_cfg = self.load_printer_settings()
        if not self.printer_cfg.get('type'): self.configure_printer(); return
        self.statusBar().showMessage(f"Sending {action}...")
        cut_val = "PART" if "Partial" in self.cut_combo.currentText() else "FULL"
        dark_val = self.darkness_spin.value()
        w = PrinterWorker(self.printer_cfg, action=action, cut_mode=cut_val, darkness=dark_val)
        w.signals.finished.connect(self.on_print_finished)
        self.threadpool.start(w)

    def on_print_finished(self, s, m):
        if s: self.statusBar().showMessage(m, 5000)
        else:
            self.statusBar().showMessage("Error. See alert.", 5000)
            QtWidgets.QMessageBox.critical(self, "Print Error", m)

class PrintDialog(QtWidgets.QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent); self.setWindowTitle("Printer Configuration")
        self.settings = settings
        lay = QtWidgets.QVBoxLayout(self)
        grp_global = QtWidgets.QGroupBox("Print Settings")
        f_glob = QtWidgets.QFormLayout(grp_global)
        self.width_px = QtWidgets.QSpinBox(); self.width_px.setRange(300, 2000)
        self.width_px.setValue(int(self.settings.value("printer/width_px", 512)))
        self.width_px.setSuffix(" px")
        self.width_px.setToolTip("Increase this if print is too small. Spec=512, but try 576 or 640 if needed.")
        f_glob.addRow("Printer Width:", self.width_px)
        lay.addWidget(grp_global)
        tabs = QtWidgets.QTabWidget()
        w_net = QtWidgets.QWidget(); f1 = QtWidgets.QFormLayout(w_net)
        self.net_h = QtWidgets.QLineEdit(self.settings.value("printer/net_host", "192.168.1.100"))
        self.net_p = QtWidgets.QSpinBox(); self.net_p.setRange(1,65535)
        self.net_p.setValue(int(self.settings.value("printer/net_port", 9100)))
        f1.addRow("IP:", self.net_h); f1.addRow("Port:", self.net_p); tabs.addTab(w_net, "Network")
        w_usb = QtWidgets.QWidget(); f2 = QtWidgets.QFormLayout(w_usb)
        self.usb_v = QtWidgets.QLineEdit(self.settings.value("printer/usb_vid", "0x04b8"))
        self.usb_p = QtWidgets.QLineEdit(self.settings.value("printer/usb_pid", "0x0202"))
        self.usb_ep_in = QtWidgets.QLineEdit(self.settings.value("printer/usb_in", "0x82"))
        self.usb_ep_out = QtWidgets.QLineEdit(self.settings.value("printer/usb_out", "0x01"))
        f2.addRow("VID:", self.usb_v); f2.addRow("PID:", self.usb_p)
        f2.addRow("EP In:", self.usb_ep_in); f2.addRow("EP Out:", self.usb_ep_out)
        tabs.addTab(w_usb, "USB")
        w_ser = QtWidgets.QWidget(); f3 = QtWidgets.QFormLayout(w_ser)
        self.ser_d = QtWidgets.QLineEdit(self.settings.value("printer/ser_dev", "/dev/ttyUSB0" if not sys.platform.startswith('win') else "COM3"))
        self.ser_b = QtWidgets.QSpinBox(); self.ser_b.setRange(1200, 115200)
        self.ser_b.setValue(int(self.settings.value("printer/ser_baud", 9600)))
        f3.addRow("Port:", self.ser_d); f3.addRow("Baud:", self.ser_b); tabs.addTab(w_ser, "Serial")
        lay.addWidget(tabs)
        saved_type = self.settings.value("printer/type", "network")
        if saved_type == "usb": tabs.setCurrentIndex(1)
        elif saved_type == "serial": tabs.setCurrentIndex(2)
        else: tabs.setCurrentIndex(0)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); lay.addWidget(bb)
        self.tabs = tabs
    def accept(self):
        self.settings.setValue("printer/width_px", self.width_px.value())
        i = self.tabs.currentIndex()
        if i == 0:
            self.settings.setValue("printer/type", "network")
            self.settings.setValue("printer/net_host", self.net_h.text())
            self.settings.setValue("printer/net_port", self.net_p.value())
        elif i == 1:
            self.settings.setValue("printer/type", "usb")
            self.settings.setValue("printer/usb_vid", self.usb_v.text())
            self.settings.setValue("printer/usb_pid", self.usb_p.text())
            self.settings.setValue("printer/usb_in", self.usb_ep_in.text())
            self.settings.setValue("printer/usb_out", self.usb_ep_out.text())
        elif i == 2:
            self.settings.setValue("printer/type", "serial")
            self.settings.setValue("printer/ser_dev", self.ser_d.text())
            self.settings.setValue("printer/ser_baud", self.ser_b.value())
        super().accept()

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    w = MainWin(); w.show()
    sys.exit(app.exec())