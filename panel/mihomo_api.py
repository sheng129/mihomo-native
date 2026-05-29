"""Mihomo REST API 客户端（curl，避免 N1 上 urllib 偶发阻塞）"""
from __future__ import annotations

import json
import subprocess
import urllib.parse
from typing import Any


class MihomoAPI:
    def __init__(self, base: str = "http://127.0.0.1:9090", secret: str = ""):
        self.base = base.rstrip("/")
        self.secret = secret

    def _curl(self, method: str, path: str, body: dict | None = None, timeout: float = 8) -> tuple[int, Any]:
        url = f"{self.base}{path}"
        cmd = ["curl", "-sS", "--max-time", str(int(max(timeout, 1))), "-X", method, url]
        if self.secret:
            cmd[1:1] = ["-H", f"Authorization: Bearer {self.secret}"]
        if body is not None:
            cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(body)])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        raw = (proc.stdout or "").strip()
        if not raw:
            if proc.returncode == 0:
                return 204, None
            return proc.returncode or 500, {"message": proc.stderr.strip() or "empty response"}
        try:
            return 200 if proc.returncode == 0 else 500, json.loads(raw)
        except json.JSONDecodeError:
            return 200, raw

    def get(self, path: str, timeout: float = 8) -> Any:
        _, data = self._curl("GET", path, timeout=timeout)
        if isinstance(data, dict) and data.get("message") and not any(k in data for k in ("proxies", "connections", "providers", "version", "meta")):
            raise RuntimeError(data["message"])
        return data

    def patch(self, path: str, body: dict) -> None:
        code, data = self._curl("PATCH", path, body)
        if code >= 400:
            raise RuntimeError(data.get("message", data) if isinstance(data, dict) else data)

    def put(self, path: str, body: dict | None = None) -> None:
        code, data = self._curl("PUT", path, body)
        if code >= 400:
            raise RuntimeError(data.get("message", data) if isinstance(data, dict) else data)

    def select_proxy(self, group: str, name: str) -> None:
        path = f"/proxies/{urllib.parse.quote(group, safe='')}"
        self.put(path, {"name": name})

    def proxy_delay(self, name: str, timeout_ms: int = 5000) -> int | None:
        q = urllib.parse.urlencode(
            {"url": "http://www.gstatic.com/generate_204", "timeout": str(timeout_ms)}
        )
        path = f"/proxies/{urllib.parse.quote(name, safe='')}/delay?{q}"
        data = self.get(path, timeout=timeout_ms / 1000 + 8)
        if isinstance(data, dict):
            d = data.get("delay")
            if isinstance(d, (int, float)) and d > 0:
                return int(d)
        return None

    def delay_test(self, group: str = "AUTO", timeout_ms: int = 8000) -> dict:
        q = urllib.parse.urlencode(
            {"url": "http://www.gstatic.com/generate_204", "timeout": str(timeout_ms)}
        )
        return self.get(
            f"/group/{urllib.parse.quote(group)}/delay?{q}",
            timeout=timeout_ms / 1000 + 15,
        )

    def auto_group_nodes(self, group: str = "AUTO") -> dict[str, Any]:
        data = self.get("/proxies", timeout=8)
        proxies = data.get("proxies", {}) if isinstance(data, dict) else {}
        auto = proxies.get(group, {})
        now = auto.get("now", "")
        skip_types = {
            "Direct",
            "Reject",
            "Selector",
            "URLTest",
            "Fallback",
            "LoadBalance",
            "Relay",
            "Compatible",
        }
        nodes: list[dict[str, Any]] = []
        for name in auto.get("all") or []:
            info = proxies.get(name, {})
            if not isinstance(info, dict):
                continue
            ptype = info.get("type", "")
            if ptype in skip_types:
                continue
            hist = info.get("history") or []
            delay = None
            if hist and isinstance(hist[-1], dict):
                delay = hist[-1].get("delay")
            nodes.append(
                {
                    "name": name,
                    "type": ptype,
                    "alive": bool(info.get("alive", True)),
                    "delay": delay,
                    "selected": name == now,
                }
            )

        def sort_key(n: dict[str, Any]) -> tuple[int, int]:
            d = n.get("delay")
            if d is None or not isinstance(d, (int, float)) or d <= 0:
                return (1, 99999)
            return (0, int(d))

        nodes.sort(key=sort_key)
        return {"group": group, "now": now, "nodes": nodes}

    def status(self) -> dict:
        version = self.get("/version", timeout=3)
        configs = self.get("/configs", timeout=3)
        auto = self.get("/proxies/AUTO", timeout=3)
        connections = self.get("/connections", timeout=3)
        providers = self.get("/providers/proxies", timeout=5)
        conns = []
        if isinstance(connections, dict):
            conns = connections.get("connections") or []
        return {
            "version": version,
            "configs": configs,
            "auto": auto,
            "connections_count": len(conns),
            "providers_runtime": providers,
        }
