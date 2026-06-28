"""config.json 로드/저장 모듈."""
from __future__ import annotations

import json
import os
from typing import Any

# config.json 은 프로젝트 루트(이 파일의 상위 디렉터리)에 둔다.
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "trigger_hotkey": "<f8>",
    "click_position": None,                # [x, y] 또는 None(클릭 생략)
    "capture_region": {"top": 100, "left": 200, "width": 800, "height": 1000},
    "save_dir": "./captures",
    "action_delay": 3.0,
    "repeat_count": 1,
    "page_turn_key": "right",
    "monitor_index": 1,
    "target_mode": "window",
    "target_window_title": None,
    "end_page": 0,
    "pages_per_view": 2,
    "auto_pdf": True,
    "capture_mode": "auto",   # "auto"(키 전송+반복) | "manual"(핫키로 1장 캡처)
}


def load_config() -> dict[str, Any]:
    """config.json 을 읽어 dict 반환. 없으면 기본값을 만들어 저장."""
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 손상 시 기본값으로 복구
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    # 누락 키는 기본값으로 보완
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def save_config(config: dict[str, Any]) -> None:
    """dict 를 config.json 으로 저장."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def resolve_save_dir(config: dict[str, Any]) -> str:
    """save_dir 을 절대경로로 변환하고 폴더 생성."""
    save_dir = config.get("save_dir", "./captures")
    if not os.path.isabs(save_dir):
        save_dir = os.path.join(_BASE_DIR, save_dir)
    os.makedirs(save_dir, exist_ok=True)
    return save_dir
