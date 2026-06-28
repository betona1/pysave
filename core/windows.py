"""열려 있는 창(프로그램) 목록 조회 및 활성화 (Windows).

창 목록은 pyautogui 와 함께 설치되는 pygetwindow 로 얻고,
포커스(포그라운드 전환)는 ctypes(user32) 로 직접 처리한다.
pygetwindow 의 activate() 는 Windows 포그라운드 잠금 때문에 자주 실패하므로,
ALT 키 트릭 + AttachThreadInput 으로 강제 전환한다.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Optional

try:
    import pygetwindow as gw
except Exception:  # pragma: no cover - 비 Windows/미설치 환경
    gw = None

# ---- ctypes user32 셋업 (64비트 HWND 정확도를 위해 argtypes 필수) ----
try:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.restype = wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _user32.AttachThreadInput.restype = wintypes.BOOL
    _user32.keybd_event.argtypes = [
        ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_void_p
    ]
    _CTYPES_OK = True
except Exception:  # pragma: no cover
    _CTYPES_OK = False

_SW_RESTORE = 9
_VK_MENU = 0x12
_KEYEVENTF_KEYUP = 0x0002
_DWMWA_EXTENDED_FRAME_BOUNDS = 9


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long), ("top", ctypes.c_long),
        ("right", ctypes.c_long), ("bottom", ctypes.c_long),
    ]


def _dwm_frame_bounds(hwnd: int):
    """DWM 기준 '보이는' 창 사각형(그림자/리사이즈 여백 제외). 실패 시 None."""
    try:
        rect = _RECT()
        res = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(_DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if res == 0:
            return rect
    except Exception:
        pass
    return None


def available() -> bool:
    """창 제어 기능 사용 가능 여부."""
    return gw is not None


def get_foreground_title() -> str:
    """현재 포그라운드(포커스) 창 제목."""
    if not _CTYPES_OK:
        return ""
    try:
        _user32.GetWindowTextW.argtypes = [
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int
        ]
        hwnd = _user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(512)
        _user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value
    except Exception:
        return ""


def is_admin() -> bool:
    """ShotKey 가 관리자 권한으로 실행 중인지."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def list_window_titles() -> list[str]:
    """제목이 있는, 보이는 창들의 제목 목록(중복 제거)."""
    return [w["title"] for w in list_windows()]


# 목록에서 제외할 시스템/셸 창들(키 입력 대상이 될 수 없는 것들)
_EXCLUDE_TITLES = {
    "Program Manager", "Microsoft Text Input Application",
    "Windows Input Experience", "ShotKey — 자동 화면 캡처",
}


def list_windows() -> list[dict]:
    """보이는 창들을 [{"title","hwnd"}] 로 반환(제목 중복 제거).

    제목이 바뀌는 앱(예: 뷰어)을 위해 안정적인 핸들(HWND)을 함께 제공한다.
    바탕화면/입력기/ShotKey 자신 등 키 입력 대상이 될 수 없는 창은 제외한다.
    """
    if gw is None:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for w in gw.getAllWindows():
        title = (w.title or "").strip()
        if not title or title in seen or title in _EXCLUDE_TITLES:
            continue
        if "ShotKey" in title:
            continue
        hwnd = _hwnd_of(w)
        if hwnd is None:
            continue
        seen.add(title)
        out.append({"title": title, "hwnd": hwnd})
    return out


def find_window(title: str):
    """제목이 정확히 일치하는 창을 우선, 없으면 부분 일치 창을 반환."""
    if gw is None or not title:
        return None
    wins = gw.getWindowsWithTitle(title)
    if not wins:
        return None
    for w in wins:
        if (w.title or "").strip() == title:
            return w
    return wins[0]


def _hwnd_of(win) -> Optional[int]:
    h = getattr(win, "_hWnd", None)
    return int(h) if h else None


_PROCESS_QUERY_LIMITED = 0x1000


def process_name(hwnd: int) -> str:
    """창을 소유한 프로세스 실행파일 이름(예: 'millie-desktop.exe')."""
    if not _CTYPES_OK or not hwnd:
        return ""
    try:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED, False, pid.value)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(512)
            if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                import os
                return os.path.basename(buf.value)
        finally:
            _kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


def _get_window_rect(hwnd: int) -> Optional[_RECT]:
    """GetWindowRect 폴백(프레임 포함)."""
    if not _CTYPES_OK:
        return None
    try:
        _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
        rect = _RECT()
        if _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return rect
    except Exception:
        pass
    return None


def region_of_hwnd(hwnd: int) -> Optional[dict]:
    """HWND 의 현재 위치/크기를 capture_region 형식으로 반환.

    DWM 보이는 사각형 → GetWindowRect → pygetwindow 순으로 시도.
    """
    if not hwnd:
        return None
    # 1) DWM 보이는 영역(그림자 제외)
    rect = _dwm_frame_bounds(hwnd)
    if rect is not None:
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w > 0 and h > 0:
            return {"left": int(rect.left), "top": int(rect.top),
                    "width": int(w), "height": int(h)}
    # 2) GetWindowRect
    rect = _get_window_rect(hwnd)
    if rect is not None:
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w > 0 and h > 0:
            return {"left": int(rect.left), "top": int(rect.top),
                    "width": int(w), "height": int(h)}
    return None


def window_region(title: str) -> Optional[dict]:
    """제목으로 창을 찾아 위치/크기를 capture_region 형식으로 반환(폴백용)."""
    w = find_window(title)
    if w is None:
        return None
    hwnd = _hwnd_of(w)
    if hwnd is not None:
        region = region_of_hwnd(hwnd)
        if region is not None:
            return region
    try:
        if w.width > 0 and w.height > 0:
            return {"left": int(w.left), "top": int(w.top),
                    "width": int(w.width), "height": int(w.height)}
    except Exception:
        pass
    return None


def activate_hwnd(hwnd: int, settle: float = 0.2, retries: int = 3) -> bool:
    """HWND 를 포커스(포그라운드)로. 성공 여부 반환."""
    if not hwnd or not _CTYPES_OK:
        return False
    for _ in range(max(1, retries)):
        if _force_foreground(hwnd):
            time.sleep(settle)
            return True
        time.sleep(0.08)
    time.sleep(settle)
    return _user32.GetForegroundWindow() == hwnd


def _force_foreground(hwnd: int) -> bool:
    """포그라운드 잠금을 우회해 hwnd 를 최상위/포커스로 만든다."""
    if not _CTYPES_OK:
        return False
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, _SW_RESTORE)

    fg = _user32.GetForegroundWindow()
    if fg == hwnd:
        return True

    cur_tid = _kernel32.GetCurrentThreadId()
    fg_tid = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
    tgt_tid = _user32.GetWindowThreadProcessId(hwnd, None)

    # ALT 키를 살짝 눌렀다 떼면 SetForegroundWindow 제한이 풀린다.
    _user32.keybd_event(_VK_MENU, 0, 0, None)
    _user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, None)

    a1 = _user32.AttachThreadInput(cur_tid, fg_tid, True) if fg_tid else False
    a2 = _user32.AttachThreadInput(cur_tid, tgt_tid, True) if tgt_tid else False
    try:
        # 주의: 여기서 ShowWindow(SW_RESTORE) 를 호출하면 최대화된 창이
        # 작은 크기로 복원되어 캡처 영역이 틀어진다. 크기는 절대 건드리지 않는다.
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        if a1:
            _user32.AttachThreadInput(cur_tid, fg_tid, False)
        if a2:
            _user32.AttachThreadInput(cur_tid, tgt_tid, False)

    return _user32.GetForegroundWindow() == hwnd


def activate_window(title: str, settle: float = 0.2, retries: int = 3) -> bool:
    """제목으로 창을 찾아 포커스(폴백용). 성공 여부 반환."""
    w = find_window(title)
    if w is None:
        return False
    hwnd = _hwnd_of(w)
    if hwnd is None:
        try:
            w.activate()
            time.sleep(settle)
            return True
        except Exception:
            return False
    return activate_hwnd(hwnd, settle=settle, retries=retries)
