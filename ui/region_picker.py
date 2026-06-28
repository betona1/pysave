"""화면 위 반투명 오버레이로 캡처 영역을 드래그 선택.

멀티모니터를 위해 가상 데스크톱 전체를 덮는 프레임리스 위젯을 띄운다.
반환 좌표는 가상 데스크톱(글로벌) 기준이라 그대로 mss.grab 에 넘길 수 있다.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class RegionPicker(QWidget):
    """드래그로 사각형 영역을 고른 뒤 region_selected 시그널 방출."""

    region_selected = pyqtSignal(dict)  # {"top","left","width","height"}
    cancelled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._origin: Optional[QPoint] = None
        self._cur: Optional[QPoint] = None
        self._virtual_origin = QPoint(0, 0)

    def start(self, bounds: Optional[dict] = None) -> None:
        """오버레이를 띄운다.

        bounds 가 주어지면 그 영역(선택한 모니터)만 덮고, 없으면 가상 데스크톱 전체.
        showFullScreen() 은 Windows 에서 한 화면에만 붙으므로 show() + setGeometry 사용.
        """
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
        self._origin = None
        self._cur = None
        self.show()
        self.raise_()
        self.activateWindow()

    # ---- 마우스 ----
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._cur = self._origin
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            self.close()

    def mouseMoveEvent(self, event) -> None:
        if self._origin is not None:
            self._cur = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        rect = QRect(self._origin, self._cur).normalized()
        if rect.width() < 3 or rect.height() < 3:
            self.cancelled.emit()
            self.close()
            return
        # 위젯 로컬좌표 -> 가상 데스크톱 글로벌좌표
        gx = self._virtual_origin.x() + rect.left()
        gy = self._virtual_origin.y() + rect.top()
        region = {
            "left": int(gx),
            "top": int(gy),
            "width": int(rect.width()),
            "height": int(rect.height()),
        }
        self.region_selected.emit(region)
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()

    # ---- 그리기 ----
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))  # 반투명 어둡게
        if self._origin is not None and self._cur is not None:
            rect = QRect(self._origin, self._cur).normalized()
            # 선택 영역만 투명하게 도려내기
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Clear
            )
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            pen = QPen(QColor(0, 200, 255), 2)
            painter.setPen(pen)
            painter.drawRect(rect)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                rect.left(), max(rect.top() - 6, 12),
                f"{rect.width()} x {rect.height()}",
            )
