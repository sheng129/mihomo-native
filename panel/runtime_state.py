"""面板运行时状态持久化。"""
from __future__ import annotations

import json

from deps import RUNTIME_STATE


def load_runtime_state() -> dict:
    if not RUNTIME_STATE.exists():
        return {}
    try:
        return json.loads(RUNTIME_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_runtime_state(data: dict) -> None:
    RUNTIME_STATE.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
