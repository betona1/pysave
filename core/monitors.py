"""멀티모니터 정보 조회 (mss 기준).

mss.monitors 리스트 규칙:
  index 0  -> 모든 모니터를 합친 가상 데스크톱 전체
  index 1.. -> 개별 모니터 (OS 나열 순서)

좌표계는 Windows 가상 데스크톱 기준이며, 주 모니터 좌상단이 (0,0)이고
왼쪽/위쪽에 있는 보조 모니터는 음수 좌표를 가질 수 있다.
PyQt 의 글로벌 좌표와 동일한 기준이므로 영역 지정 결과를 그대로 mss 에 넘길 수 있다.
"""
from __future__ import annotations

from typing import Any

import mss


def list_monitors() -> list[dict[str, Any]]:
    """모니터 목록을 반환.

    반환 형식:
      [{"index": 1, "left":, "top":, "width":, "height":, "label": "모니터 1 (1920x1080)"}...]
    index 0(전체 가상 데스크톱)은 맨 앞에 "전체(모든 모니터)" 로 포함한다.
    """
    result: list[dict[str, Any]] = []
    with mss.mss() as sct:
        for i, mon in enumerate(sct.monitors):
            entry = {
                "index": i,
                "left": mon["left"],
                "top": mon["top"],
                "width": mon["width"],
                "height": mon["height"],
            }
            if i == 0:
                entry["label"] = (
                    f"전체 가상 데스크톱 ({mon['width']}x{mon['height']})"
                )
            else:
                entry["label"] = (
                    f"모니터 {i} — {mon['width']}x{mon['height']} "
                    f"@({mon['left']},{mon['top']})"
                )
            result.append(entry)
    return result


def get_monitor(index: int) -> dict[str, Any] | None:
    """index 에 해당하는 모니터 정보(dict) 반환. 없으면 None."""
    for mon in list_monitors():
        if mon["index"] == index:
            return mon
    return None


def monitor_region(index: int) -> dict[str, int] | None:
    """선택한 모니터 전체를 capture_region 형식으로 반환."""
    mon = get_monitor(index)
    if mon is None:
        return None
    return {
        "top": mon["top"],
        "left": mon["left"],
        "width": mon["width"],
        "height": mon["height"],
    }
