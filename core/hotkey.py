"""pynput 전역 핫키 리스너 (별도 스레드).

핫키 감지 콜백에서 직접 GUI 를 건드리면 크래시하므로,
QObject 의 pyqtSignal 로 PyQt 메인 스레드에 전달한다.
자동화가 스스로 보낸 키 입력으로 다시 트리거되는 무한루프를 막기 위해
suppress 플래그를 둔다 (자동화 실행 중에는 핫키 무시).
"""
from __future__ import annotations

import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard


class HotkeyManager(QObject):
    """전역 핫키를 감지해 triggered 시그널을 방출."""

    triggered = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._listener: Optional[keyboard.GlobalHotKeys] = None
        self._hotkey: str = "<f8>"
        self._suppressed = threading.Event()  # set 이면 트리거 무시

    def set_suppressed(self, value: bool) -> None:
        """자동화 동작 중 True 로 설정하면 핫키 입력을 무시한다."""
        if value:
            self._suppressed.set()
        else:
            self._suppressed.clear()

    def _on_activate(self) -> None:
        if self._suppressed.is_set():
            return
        self.triggered.emit()

    def start(self, hotkey: str) -> bool:
        """hotkey(pynput 형식, 예: '<f8>', '<ctrl>+<alt>+s', '<right>') 리스너 시작."""
        self.stop()
        self._hotkey = hotkey
        try:
            self._listener = keyboard.GlobalHotKeys({hotkey: self._on_activate})
            self._listener.start()  # 내부적으로 별도 데몬 스레드에서 실행
            return True
        except Exception as exc:  # 잘못된 핫키 형식 등
            self._listener = None
            self.error.emit(f"핫키 등록 실패: {hotkey} ({exc})")
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def is_running(self) -> bool:
        return self._listener is not None
