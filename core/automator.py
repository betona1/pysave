"""pyautogui 로 대상(좌표 또는 창)에 포커스 후 페이지 넘김 키 입력."""
from __future__ import annotations

import time
from typing import Optional, Sequence

import pyautogui

from . import keyboard, windows

# 안전장치: 마우스를 화면 좌상단으로 옮기면 중단됨. (의도된 기능 — 끄지 말 것)
pyautogui.FAILSAFE = True


def do_action(
    click_xy: Optional[Sequence[int]] = None,
    page_turn_key: str = "right",
    delay: float = 0.3,
    target_mode: str = "click",
    target_window_title: Optional[str] = None,
    target_window_hwnd: Optional[int] = None,
) -> dict:
    """대상에 포커스 후 페이지 넘김 키 전송.

    target_mode:
      "click"  -> click_xy 좌표를 클릭해 포커스 (click_xy 가 None 이면 클릭 생략)
      "window" -> HWND(있으면) 또는 제목으로 창을 활성화해 포커스
    page_turn_key : 'right' 등 pyautogui.press 에 넘길 키 이름
    delay : 포커스 후 / 키 입력 후 렌더링 대기 시간(초)

    반환: window 모드면 포커스 성공 여부(True/False), 그 외엔 None.
    """
    focus_ok: Optional[bool] = None
    fg_title = ""
    if target_mode == "window":
        if target_window_hwnd:
            focus_ok = windows.activate_hwnd(int(target_window_hwnd))
        elif target_window_title:
            focus_ok = windows.activate_window(target_window_title)
        # 포커스 안정화 대기 후 실제 포그라운드 창 확인
        time.sleep(min(delay, 0.4))
        fg_title = windows.get_foreground_title()
    elif click_xy:
        pyautogui.click(int(click_xy[0]), int(click_xy[1]))  # 좌표 클릭 포커스
        time.sleep(min(delay, 0.4))

    # 다음 페이지: SendInput(확장키 플래그 포함) 우선, 실패 시 pyautogui 폴백
    if not keyboard.send_key(page_turn_key):
        pyautogui.press(page_turn_key)
    time.sleep(delay)               # 페이지 전환 렌더링 대기
    return {"focus_ok": focus_ok, "fg_title": fg_title}
