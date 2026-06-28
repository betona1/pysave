"""mss 기반 영역 스크린샷 + 저장."""
from __future__ import annotations

import os
from typing import Any

import mss
import mss.tools


def capture(region: dict[str, int], path: str) -> str:
    """region 영역을 잡아 path(.png)로 저장.

    region = {"top":, "left":, "width":, "height":}  (가상 데스크톱 절대 좌표)
    좌표는 음수도 허용(주 모니터 왼쪽/위쪽 보조 모니터).
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with mss.mss() as sct:
        img = sct.grab(region)
        mss.tools.to_png(img.rgb, img.size, output=path)
    return path


def page_path(save_dir: str, n: int) -> str:
    """page_{n:03d}.png 형식 경로 생성."""
    return os.path.join(save_dir, f"page_{n:03d}.png")


def next_page_index(save_dir: str) -> int:
    """save_dir 안의 기존 page_NNN.png 중 가장 큰 번호 + 1 반환 (없으면 1)."""
    if not os.path.isdir(save_dir):
        return 1
    max_n = 0
    for name in os.listdir(save_dir):
        if name.startswith("page_") and name.endswith(".png"):
            num = name[len("page_"):-len(".png")]
            if num.isdigit():
                max_n = max(max_n, int(num))
    return max_n + 1
