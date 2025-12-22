from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

PX_PER_MM = 8.0   # keep this in sync with your Template width_px/height_px logic
DPI = 203


class RulerView(QtWidgets.QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setRenderHints(
            QtGui.QPainter.Antialiasing
            | QtGui.QPainter.TextAntialiasing
            | QtGui.QPainter.SmoothPixmapTransform
        )
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)

        # Zoom/pan behavior
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)

        self._show_margins = True
        self._panning = False
        self._pan_last_pos = QtCore.QPoint()
        
        self._space_held = False

    # ------------ public toggle used by MainWindow ------------
    def setShowMargins(self, show: bool):
        self._show_margins = bool(show)
        self.viewport().update()

    # ------------ background: workspace + page outline ------------
    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        # workspace
        painter.fillRect(rect, QtGui.QColor("#2b2b2b"))

        if self.scene() is None:
            return

        scene_rect = self.sceneRect()

        # white page area (scene coordinates)
        page_rect = QtCore.QRectF(
            scene_rect.left(),
            scene_rect.top(),
            scene_rect.width(),
            scene_rect.height(),
        )
        painter.fillRect(page_rect, QtCore.Qt.white)

        # subtle gray border around the paper
        pen = QtGui.QPen(QtGui.QColor("#999999"))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(page_rect)

    # ------------ foreground: margins + rulers ------------
    def drawForeground(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        super().drawForeground(painter, rect)

        scene = self.scene()
        if scene is None:
            return

        # First: draw printable area (margins) in scene coordinates
        if self._show_margins:
            paper_w = float(scene.property("paper_width") or 0)
            paper_h = float(scene.property("paper_height") or 0)

            margins_mm = getattr(scene, "margins_mm", (4.0, 0.0, 4.0, 0.0))
            try:
                m_left, m_top, m_right, m_bottom = margins_mm
            except Exception:
                m_left = m_top = m_right = m_bottom = 4.0

            # convert margins mm -> px in scene coordinates
            ml = m_left * PX_PER_MM
            mt = m_top * PX_PER_MM
            mr = m_right * PX_PER_MM
            mb = m_bottom * PX_PER_MM

            margin_rect = QtCore.QRectF(
                ml,
                mt,
                paper_w - ml - mr,
                paper_h - mt - mb,
            )

            pen = QtGui.QPen(QtGui.QColor("#ff5555"))
            pen.setStyle(QtCore.Qt.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)

            # If there is no top/bottom margin, only draw left/right lines.
            if m_top == 0 and m_bottom == 0:
                scene_rect = scene.sceneRect()
                top_y = scene_rect.top()
                bottom_y = scene_rect.top() + paper_h
                # left margin line
                painter.drawLine(ml, top_y, ml, bottom_y)
                # right margin line
                painter.drawLine(paper_w - mr, top_y, paper_w - mr, bottom_y)
            else:
                painter.drawRect(margin_rect)


        # Second: draw rulers in VIEW coordinates so they stick to the edges
        self._draw_rulers(painter)

    # ------------ rulers implementation ------------
    def _draw_rulers(self, painter: QtGui.QPainter) -> None:
        scene = self.scene()
        if scene is None:
            return

        viewport_rect = self.viewport().rect()
        if viewport_rect.isEmpty():
            return

        ruler_thickness = 20  # px
        bg_color = QtGui.QColor("#3c3c3c")
        line_color = QtGui.QColor("#bbbbbb")
        text_color = QtGui.QColor("#ffffff")

        # Determine which part of the SCENE is visible
        tl_scene = self.mapToScene(viewport_rect.topLeft())
        br_scene = self.mapToScene(viewport_rect.bottomRight())
        visible_scene = QtCore.QRectF(tl_scene, br_scene)

        # Paper / page size in scene units (px)
        paper_w = float(scene.property("paper_width") or 0)
        paper_h = float(scene.property("paper_height") or 0)
        page_rect_scene = QtCore.QRectF(0, 0, paper_w, paper_h)

        # Intersection of visible region with page
        visible_page = visible_scene.intersected(page_rect_scene)
        if visible_page.isEmpty():
            # we're panned completely off the page
            return

        # Convert those extents to mm (0,0 at top-left of page)
        start_x_mm = max(0.0, visible_page.left() / PX_PER_MM)
        end_x_mm = max(0.0, visible_page.right() / PX_PER_MM)
        start_y_mm = max(0.0, visible_page.top() / PX_PER_MM)
        end_y_mm = max(0.0, visible_page.bottom() / PX_PER_MM)

        # Ruler steps in mm
        major_step_mm = 10.0
        minor_step_mm = 2.0

        # Prepare painter for VIEW coordinates
        painter.save()
        painter.resetTransform()

        # Ruler backgrounds
        painter.fillRect(
            0,
            0,
            viewport_rect.width(),
            ruler_thickness,
            bg_color,
        )
        painter.fillRect(
            0,
            0,
            ruler_thickness,
            viewport_rect.height(),
            bg_color,
        )

        pen_minor = QtGui.QPen(line_color)
        pen_minor.setWidth(1)
        pen_major = QtGui.QPen(text_color)
        pen_major.setWidth(1)

        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)

        import math

        # ---- Top ruler (horizontal) ----
        first_mm_x = math.floor(start_x_mm / minor_step_mm) * minor_step_mm
        cur_mm = first_mm_x
        while cur_mm <= end_x_mm:
            x_scene = cur_mm * PX_PER_MM
            pt_view = self.mapFromScene(QtCore.QPointF(x_scene, 0))
            x = int(pt_view.x())

            if x < ruler_thickness:  # don't draw under the vertical ruler
                cur_mm += minor_step_mm
                continue

            is_major = (cur_mm % major_step_mm) == 0
            if is_major:
                painter.setPen(pen_major)
                tick_len = ruler_thickness - 4
            else:
                painter.setPen(pen_minor)
                tick_len = ruler_thickness // 2

            painter.drawLine(x, 0, x, tick_len)

            if is_major:
                label = f"{int(cur_mm)}"
                painter.drawText(
                    x + 2,
                    ruler_thickness - 4,
                    label,
                )

            cur_mm += minor_step_mm

        # ---- Left ruler (vertical) ----
        first_mm_y = math.floor(start_y_mm / minor_step_mm) * minor_step_mm
        cur_mm = first_mm_y
        while cur_mm <= end_y_mm:
            y_scene = cur_mm * PX_PER_MM
            pt_view = self.mapFromScene(QtCore.QPointF(0, y_scene))
            y = int(pt_view.y())

            if y < ruler_thickness:  # don't draw under the top ruler
                cur_mm += minor_step_mm
                continue

            is_major = (cur_mm % major_step_mm) == 0
            if is_major:
                painter.setPen(pen_major)
                tick_len = ruler_thickness - 4
            else:
                painter.setPen(pen_minor)
                tick_len = ruler_thickness // 2

            painter.drawLine(0, y, tick_len, y)

            if is_major:
                label = f"{int(cur_mm)}"
                painter.drawText(
                    2,
                    y - 2,
                    label,
                )

            cur_mm += minor_step_mm

        painter.restore()
    
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key_Space:
            if not self._space_held:
                self._space_held = True
                # If not already actively panning, show open hand
                if not self._panning:
                    self.setCursor(QtCore.Qt.OpenHandCursor)
            event.accept()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key_Space:
            self._space_held = False
            # Only reset cursor if not actively panning with mouse
            if not self._panning:
                self.setCursor(QtCore.Qt.ArrowCursor)
            event.accept()
            return

        super().keyReleaseEvent(event)


    # ------------ zoom & pan ------------
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """
        Ctrl + wheel = zoom around cursor.
        Plain wheel = normal scroll (default behavior).
        """
        if event.modifiers() & QtCore.Qt.ControlModifier:
            angle = event.angleDelta().y()
            if angle == 0:
                return

            zoom_factor = 1.2 if angle > 0 else 1 / 1.2
            self.scale(zoom_factor, zoom_factor)
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        # Middle button OR Space+Left = pan
        if event.button() == QtCore.Qt.MiddleButton or (
            event.button() == QtCore.Qt.LeftButton and self._space_held
        ):
            self._panning = True
            self._pan_last_pos = event.pos()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._panning:
            delta = event.pos() - self._pan_last_pos
            self._pan_last_pos = event.pos()

            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - delta.x())
            vbar.setValue(vbar.value() - delta.y())

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._panning and (
            event.button() == QtCore.Qt.MiddleButton
            or event.button() == QtCore.Qt.LeftButton
        ):
            self._panning = False
            # If space is still held, keep hand cursor; otherwise revert
            self.setCursor(QtCore.Qt.ClosedHandCursor if self._space_held else QtCore.Qt.ArrowCursor)
            event.accept()
            return

        super().mouseReleaseEvent(event)

