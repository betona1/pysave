"""캡처 반복 시퀀스를 별도 스레드(QThread)에서 실행.

GUI 블로킹을 막기 위해 반복 루프(클릭/키입력/대기/스크린샷)를 워커에서 돌리고,
진행 상황을 시그널로 메인 스레드에 알린다.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from . import automator, capturer


class CaptureWorker(QThread):
    """repeat_count 만큼 [포커스 → 페이지넘김 → 캡처] 를 반복."""

    progress = pyqtSignal(int, int, str)  # (현재, 전체, 저장경로)
    note = pyqtSignal(str)                # 진행 중 경고/안내
    finished_ok = pyqtSignal(int)         # 저장한 장수
    failed = pyqtSignal(str)

    def __init__(self, config: dict[str, Any], save_dir: str,
                 skip_action: bool = False) -> None:
        super().__init__()
        self._config = config
        self._save_dir = save_dir
        self._stop = False
        # skip_action=True 면 키 전송/포커스 없이 '캡처만' 한다(수동 모드).
        self._skip_action = skip_action

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        cfg = self._config
        region = cfg["capture_region"]
        repeat = max(1, int(cfg.get("repeat_count", 1)))
        delay = float(cfg.get("action_delay", 0.3))
        key = cfg.get("page_turn_key", "right")
        click_xy = cfg.get("click_position")
        target_mode = cfg.get("target_mode", "click")
        target_title = cfg.get("target_window_title")
        target_hwnd = cfg.get("target_window_hwnd")

        start_n = capturer.next_page_index(self._save_dir)
        saved = 0
        try:
            for i in range(repeat):
                if self._stop:
                    break
                if self._skip_action:
                    # 수동 모드: 키 전송/포커스 없이, 지정한 딜레이만 대기 후 캡처
                    import time
                    time.sleep(delay)
                else:
                    # 1) 대상 포커스 + 페이지 넘김 키
                    info = automator.do_action(
                        click_xy=click_xy,
                        page_turn_key=key,
                        delay=delay,
                        target_mode=target_mode,
                        target_window_title=target_title,
                        target_window_hwnd=target_hwnd,
                    )
                    if target_mode == "window":
                        fg = info.get("fg_title", "")
                        self.note.emit(
                            f"  포커스 창='{fg}' (대상='{target_title}', "
                            f"활성화={info.get('focus_ok')})"
                        )
                        if target_title and fg and target_title not in fg and fg not in target_title:
                            self.note.emit(
                                "  ⚠ 키가 대상이 아닌 다른 창으로 가고 있습니다 "
                                "(밀리의서재가 맨 앞으로 오지 않음)"
                            )
                if self._stop:
                    break
                # 2) 스크린샷 저장
                path = capturer.page_path(self._save_dir, start_n + i)
                capturer.capture(region, path)
                saved += 1
                self.progress.emit(i + 1, repeat, path)
            self.finished_ok.emit(saved)
        except Exception as exc:
            self.failed.emit(str(exc))
