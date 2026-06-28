"""모니터 식별: 각 모니터 한가운데에 큰 번호를 잠시 표시한다.

Windows 디스플레이 설정의 '식별' 기능과 동일한 UX.
번호는 mss 의 모니터 index(1부터)와 일치시켜, 선택 콤보박스와 매칭된다.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QWidget

from core import monitors


class _NumberOverlay(QWidget):
    def __init__(self, number: int, left: int, top: int, width: int, height: int):
        super().__init__()
        self._number = number
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(left, top, width, height)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 살짝 어두운 배경 박스
        box_w = min(260, self.width() - 40)
        box_h = min(260, self.height() - 40)
        cx, cy = self.width() // 2, self.height() // 2
        box = self.rect().adjusted(0, 0, 0, 0)
        box.setWidth(box_w)
        box.setHeight(box_h)
        box.moveCenter(self.rect().center())
        painter.setBrush(QColor(0, 120, 215, 220))  # Windows 파랑
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(box, 24, 24)
        # 번호
        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPointSize(120)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, str(self._number))


class MonitorIdentifier:
    """모든 모니터에 번호를 표시하고 일정 시간 후 자동으로 닫는다."""

    def __init__(self) -> None:
        self._overlays: list[_NumberOverlay] = []

    def show(self, duration_ms: int = 2000) -> None:
        self.close()
        for mon in monitors.list_monitors():
            if mon["index"] == 0:
                continue  # 전체 가상 데스크톱은 건너뜀
            ov = _NumberOverlay(
                mon["index"], mon["left"], mon["top"],
                mon["width"], mon["height"],
            )
            ov.show()
            self._overlays.append(ov)
        QTimer.singleShot(duration_ms, self.close)

    def close(self) -> None:
        for ov in self._overlays:
            ov.close()
        self._overlays.clear()
