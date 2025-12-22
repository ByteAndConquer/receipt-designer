from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets

def scene_to_image(scene: QtWidgets.QGraphicsScene, scale: float = 1.0) -> QtGui.QImage:
    rect = scene.sceneRect()
    img = QtGui.QImage(int(rect.width()*scale), int(rect.height()*scale), QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.white)
    painter = QtGui.QPainter(img)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.scale(scale, scale)
    scene.render(painter, QtCore.QRectF(img.rect()), rect)
    painter.end()
    return img
