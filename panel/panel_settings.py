"""面板设置：主题、密码等"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

SETTINGS_PATH = Path(os.environ.get("PANEL_SETTINGS_PATH", "/etc/n1-panel/settings.json"))
ENV_PATH = Path(os.environ.get("PANEL_ENV_PATH", "/etc/n1-panel/env"))
DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "dark",
    "devices_refresh_sec": 15,
    "dashboard_auto_refresh": False,
    "auto_switch_enabled": True,
    "auto_switch_interval_sec": 300,
    "traffic_failover_enabled": True,
    "traffic_failover_threshold": 100,
    "node_test_cooldown_sec": 600,
    "default_device_policy": "direct",
}


def _load_file() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**DEFAULT_SETTINGS, **data}
    except (json.JSONDecodeError, OSError):
        pass
    return dict(DEFAULT_SETTINGS)


def get_settings() -> dict[str, Any]:
    data = _load_file()
    return {
        "theme": data.get("theme", "dark"),
        "devices_refresh_sec": int(data.get("devices_refresh_sec", 15)),
        "dashboard_auto_refresh": bool(data.get("dashboard_auto_refresh", False)),
        "auto_switch_enabled": bool(data.get("auto_switch_enabled", True)),
        "auto_switch_interval_sec": int(data.get("auto_switch_interval_sec", 300)),
        "traffic_failover_enabled": bool(data.get("traffic_failover_enabled", True)),
        "traffic_failover_threshold": int(data.get("traffic_failover_threshold", 100)),
        "node_test_cooldown_sec": int(data.get("node_test_cooldown_sec", 600)),
        "default_device_policy": data.get("default_device_policy", "direct"),
        "panel_port": int(os.environ.get("PANEL_PORT", "8088")),
    }


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    data = _load_file()
    theme = updates.get("theme")
    if theme is not None:
        if theme not in ("dark", "light", "system"):
            raise ValueError("theme 必须是 dark / light / system")
        data["theme"] = theme
    if "devices_refresh_sec" in updates and updates["devices_refresh_sec"] is not None:
        sec = int(updates["devices_refresh_sec"])
        if sec < 5 or sec > 300:
            raise ValueError("刷新间隔需在 5–300 秒")
        data["devices_refresh_sec"] = sec
    if "dashboard_auto_refresh" in updates:
        data["dashboard_auto_refresh"] = bool(updates["dashboard_auto_refresh"])
    if "auto_switch_enabled" in updates:
        data["auto_switch_enabled"] = bool(updates["auto_switch_enabled"])
    if "traffic_failover_enabled" in updates:
        data["traffic_failover_enabled"] = bool(updates["traffic_failover_enabled"])
    if "auto_switch_interval_sec" in updates and updates["auto_switch_interval_sec"] is not None:
        sec = int(updates["auto_switch_interval_sec"])
        if sec < 30 or sec > 3600:
            raise ValueError("自动切换检查间隔需在 30–3600 秒")
        data["auto_switch_interval_sec"] = sec
    if "traffic_failover_threshold" in updates and updates["traffic_failover_threshold"] is not None:
        pct = int(updates["traffic_failover_threshold"])
        if pct < 80 or pct > 100:
            raise ValueError("流量切换阈值需在 80–100")
        data["traffic_failover_threshold"] = pct
    if "node_test_cooldown_sec" in updates and updates["node_test_cooldown_sec"] is not None:
        sec = int(updates["node_test_cooldown_sec"])
        if sec < 60 or sec > 3600:
            raise ValueError("节点测速冷却需在 60–3600 秒")
        data["node_test_cooldown_sec"] = sec
    if "default_device_policy" in updates and updates["default_device_policy"] is not None:
        pol = str(updates["default_device_policy"]).strip()
        if pol not in ("proxy", "direct"):
            raise ValueError("default_device_policy 必须是 proxy 或 direct")
        data["default_device_policy"] = pol
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_settings()


def _read_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def change_password(old_password: str, new_password: str, current_password: str) -> None:
    if old_password != current_password:
        raise ValueError("当前密码不正确")
    if len(new_password) < 4:
        raise ValueError("新密码至少 4 位")
    if not ENV_PATH.exists():
        raise ValueError("未找到环境配置文件")
    text = ENV_PATH.read_text(encoding="utf-8")
    if re.search(r"^PANEL_PASSWORD=", text, flags=re.MULTILINE):
        text = re.sub(
            r"^PANEL_PASSWORD=.*$",
            f"PANEL_PASSWORD={new_password}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        text = text.rstrip() + f"\nPANEL_PASSWORD={new_password}\n"
    ENV_PATH.write_text(text, encoding="utf-8")
    os.environ["PANEL_PASSWORD"] = new_password


def restart_panel() -> tuple[bool, str]:
    proc = subprocess.run(
        ["systemctl", "restart", "n1-panel"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()
