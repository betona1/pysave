"""실제 키보드와 동일하게 키를 보내는 모듈 (Windows SendInput).

pyautogui.press 는 방향키 같은 '확장 키(extended key)'에 EXTENDEDKEY 플래그를
제대로 넣지 않아, Chromium/Flutter 기반 앱 등에서 입력이 무시되는 경우가 있다.
여기서는 스캔코드 + 확장키 플래그로 SendInput 을 직접 호출해 물리 키보드처럼 보낸다.

주의: x64 에서 INPUT 구조체 크기는 반드시 40바이트여야 한다(union 이 MOUSEINPUT
크기로 잡힘). 작게 만들면 SendInput 이 ERROR_INVALID_PARAMETER(87)로 조용히 실패한다.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

try:
    _user32 = ctypes.windll.user32
    _CTYPES_OK = True
except Exception:  # pragma: no cover
    _CTYPES_OK = False

# 포인터 크기 정수 (x64=8, x86=4)
ULONG_PTR = ctypes.c_size_t

# 가상 키 코드
_VK = {
    "right": 0x27, "left": 0x25, "up": 0x26, "down": 0x28,
    "pagedown": 0x22, "pgdn": 0x22, "pageup": 0x21, "pgup": 0x21,
    "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E, "del": 0x2E,
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
    "esc": 0x1B, "escape": 0x1B, "backspace": 0x08,
}
# 확장 키(내비게이션 클러스터) — EXTENDEDKEY 플래그 필요
_EXTENDED = {
    "right", "left", "up", "down", "pagedown", "pgdn", "pageup", "pgup",
    "home", "end", "insert", "delete", "del",
}

_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_SCANCODE = 0x0008
_INPUT_KEYBOARD = 1
_MAPVK_VK_TO_VSC = 0


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


if _CTYPES_OK:
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT
    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _user32.MapVirtualKeyW.restype = wintypes.UINT


def _send_scancode(scan: int, extended: bool, keyup: bool) -> bool:
    flags = _KEYEVENTF_SCANCODE
    if extended:
        flags |= _KEYEVENTF_EXTENDEDKEY
    if keyup:
        flags |= _KEYEVENTF_KEYUP
    inp = _INPUT()
    inp.type = _INPUT_KEYBOARD
    inp.ki = _KEYBDINPUT(0, scan, flags, 0, 0)
    sent = _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
    return sent == 1


def can_send(key_name: str) -> bool:
    return _CTYPES_OK and key_name.strip().lower() in _VK


def send_key(key_name: str) -> bool:
    """키 한 번(누름→뗌)을 SendInput 으로 전송. 실제 주입 성공 여부 반환.

    매핑에 없거나 SendInput 실패 시 False (호출측에서 pyautogui 폴백)."""
    name = key_name.strip().lower()
    if not _CTYPES_OK or name not in _VK:
        return False
    vk = _VK[name]
    scan = _user32.MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC)
    if not scan:
        return False
    extended = name in _EXTENDED
    ok_down = _send_scancode(scan, extended, keyup=False)
    ok_up = _send_scancode(scan, extended, keyup=True)
    return ok_down and ok_up
