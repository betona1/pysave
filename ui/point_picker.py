"""화면을 클릭해 좌표 한 점을 지정하는 반투명 오버레이.

'좌표 클릭' 모드에서, 키를 보내기 전 대상 창에 포커스를 주기 위해
클릭할 지점을 마우스로 직접 찍어 고른다(멀티모니터 가상좌표 지원).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class PointPicker(QWidget):
    """클릭한 위치를 글로벌 좌표 [x, y] 로 point_selected 시그널 방출."""

    point_selected = pyqtSignal(int, int)
    cancelled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._cur: Optional[QPoint] = None
        self._virtual_origin = QPoint(0, 0)

    def start(self, bounds: Optional[dict] = None) -> None:
        if bounds:
            rect = QRect(
                int(bounds["left"]), int(bounds["top"]),
                int(bounds["width"]), int(bounds["height"]),
            )
        else:
            rect = QRect()
            for screen in QGuiApplication.screens():
                rect = rect.united(screen.geometry())
        self._virtual_origin = rect.topLeft()
        self.setGeometry(rect)
        self._cur = None
        self.show()
        self.raise_()
        self.activateWindow()

    def mouseMoveEvent(self, event) -> None:
        self._cur = event.position().toPoint()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            p = event.position().toPoint()
            gx = self._virtual_origin.x() + p.x()
            gy = self._virtual_origin.y() + p.y()
            self.point_selected.emit(int(gx), int(gy))
            self.close()
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))
        if self._cur is not None:
            pen = QPen(QColor(0, 200, 255), 1)
            painter.setPen(pen)
            # 십자선
            painter.drawLine(0, self._cur.y(), self.width(), self._cur.y())
            painter.drawLine(self._cur.x(), 0, self._cur.x(), self.height())
            # 좌표 텍스트(글로벌)
            gx = self._virtual_origin.x() + self._cur.x()
            gy = self._virtual_origin.y() + self._cur.y()
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(self._cur.x() + 12, self._cur.y() - 8, f"({gx}, {gy})")
