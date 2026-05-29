"""流量历史与配额"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from utils import bytes_to_gb

DATA_DIR = Path(os.environ.get("PANEL_DATA_DIR", "/var/lib/n1-panel"))
QUOTA_PATH = Path(os.environ.get("PANEL_QUOTA_PATH", "/etc/n1-panel/quotas.json"))
HISTORY_PATH = DATA_DIR / "traffic_history.json"
SNAPSHOT_INTERVAL = int(os.environ.get("TRAFFIC_SNAPSHOT_SEC", "300"))
MAX_POINTS = 288  # 约 24h @5min


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data: Any) -> None:
    _ensure_dirs()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def get_quotas() -> dict[str, Any]:
    return _load_json(QUOTA_PATH, {"providers": {}})


def set_provider_quota(name: str, limit_gb: float | None, alert_percent: int = 80) -> dict:
    data = get_quotas()
    providers = data.setdefault("providers", {})
    if limit_gb is None or limit_gb <= 0:
        providers.pop(name, None)
    else:
        providers[name] = {"limit_gb": float(limit_gb), "alert_percent": int(alert_percent)}
    _save_json(QUOTA_PATH, data)
    return data


def _parse_sub_info(info: dict | None) -> dict[str, Any]:
    if not info:
        return {
            "upload": 0, "download": 0, "total": 0, "used": 0, "expire": None,
            "used_gb": 0.0, "total_gb": None, "upload_gb": 0.0, "download_gb": 0.0,
        }
    up = int(info.get("Upload") or info.get("upload") or 0)
    down = int(info.get("Download") or info.get("download") or 0)
    total = int(info.get("Total") or info.get("total") or 0)
    expire = info.get("Expire") or info.get("expire")
    return {
        "upload": up,
        "download": down,
        "total": total,
        "used": up + down,
        "expire": expire,
        "used_gb": round(bytes_to_gb(up + down), 2),
        "total_gb": round(bytes_to_gb(total), 2) if total else None,
        "upload_gb": round(bytes_to_gb(up), 2),
        "download_gb": round(bytes_to_gb(down), 2),
    }


def record_snapshot(providers_runtime: dict | None, *, known_names: set[str] | None = None) -> None:
    """按间隔记录各机场流量快照"""
    if not providers_runtime:
        return
    history = _load_json(HISTORY_PATH, {"last_ts": 0, "series": {}})
    now = time.time()
    if now - history.get("last_ts", 0) < SNAPSHOT_INTERVAL:
        return

    series: dict[str, list] = history.setdefault("series", {})
    ts = datetime.now().strftime("%H:%M")
    for name, prov in (providers_runtime.get("providers") or {}).items():
        if known_names is not None and name not in known_names:
            continue
        info = _parse_sub_info(prov.get("subscriptionInfo"))
        points = series.setdefault(name, [])
        points.append({"t": ts, "used_gb": info["used_gb"], "up_gb": info["upload_gb"], "down_gb": info["download_gb"]})
        if len(points) > MAX_POINTS:
            series[name] = points[-MAX_POINTS:]

    history["last_ts"] = now
    _save_json(HISTORY_PATH, history)


def traffic_report(providers_runtime: dict | None, *, known_names: set[str] | None = None) -> dict[str, Any]:
    record_snapshot(providers_runtime, known_names=known_names)
    quotas = get_quotas()
    history = _load_json(HISTORY_PATH, {"series": {}})
    providers = []

    for name, prov in ((providers_runtime or {}).get("providers") or {}).items():
        if known_names is not None and name not in known_names:
            continue
        info = _parse_sub_info(prov.get("subscriptionInfo"))
        q = quotas.get("providers", {}).get(name, {})
        limit_gb = q.get("limit_gb")
        alert_pct = q.get("alert_percent", 80)
        used_gb = info["used_gb"]
        pct = None
        alert = False
        if limit_gb and limit_gb > 0:
            pct = round(used_gb / limit_gb * 100, 1)
            alert = pct >= alert_pct
        elif info["total_gb"]:
            pct = round(used_gb / info["total_gb"] * 100, 1) if info["total_gb"] else None
            alert = pct is not None and pct >= alert_pct

        providers.append(
            {
                "name": name,
                **info,
                "limit_gb": limit_gb,
                "alert_percent": alert_pct,
                "usage_percent": pct,
                "alert": alert,
                "history": history.get("series", {}).get(name, []),
            }
        )

    return {"providers": providers, "updated_at": datetime.now().isoformat(timespec="seconds")}
