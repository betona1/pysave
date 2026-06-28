"""키 조합을 한 번 입력받아 pynput 핫키 문자열로 변환하는 다이얼로그.

예) F8        -> "<f8>"
    Ctrl+Alt+S -> "<ctrl>+<alt>+s"
    오른쪽 화살표 -> "<right>"
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout
from pynput import keyboard

_MODS = {
    keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
    keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr,
    keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r,
    keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
}


def _mod_name(key) -> Optional[str]:
    if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        return "<ctrl>"
    if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
               keyboard.Key.alt_gr):
        return "<alt>"
    if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
        return "<shift>"
    if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
        return "<cmd>"
    return None


def _main_key(key) -> Optional[str]:
    """비-수정자 키를 pynput 핫키 토큰으로."""
    if isinstance(key, keyboard.KeyCode):
        if key.char:
            return key.char.lower()
        return None
    if isinstance(key, keyboard.Key):
        return f"<{key.name}>"
    return None


class HotkeyCaptureDialog(QDialog):
    """단축키 한 번 입력받음. 성공 시 accept()되고 self.result_hotkey 설정."""

    _captured = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("핫키 입력")
        self.setModal(True)
        self.result_hotkey: Optional[str] = None
        layout = QVBoxLayout(self)
        self._label = QLabel("원하는 키(조합)를 눌러주세요…\n(Esc: 취소)")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)
        self.resize(320, 120)

        self._mods: list[str] = []
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._captured.connect(self._finish)
        self._listener.start()

    def _on_press(self, key) -> None:
        if key == keyboard.Key.esc:
            self._captured.emit("")  # 취소
            return
        mod = _mod_name(key)
        if mod is not None:
            if mod not in self._mods:
                self._mods.append(mod)
            return
        main = _main_key(key)
        if main is None:
            return
        combo = "+".join(self._mods + [main])
        self._captured.emit(combo)

    def _finish(self, combo: str) -> None:
        try:
            self._listener.stop()
        except Exception:
            pass
        if combo:
            self.result_hotkey = combo
            self.accept()
        else:
            self.reject()

    def closeEvent(self, event) -> None:
        try:
            self._listener.stop()
        except Exception:
            pass
        super().closeEvent(event)
