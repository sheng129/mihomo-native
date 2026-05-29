"""读写 /opt/mihomo/config/config.yaml"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

MIHOMO_BIN = os.environ.get("MIHOMO_BIN", "/opt/mihomo/core/mihomo")
CONFIG_DIR = Path(os.environ.get("MIHOMO_CONFIG_DIR", "/opt/mihomo/config"))
CONFIG_PATH = CONFIG_DIR / "config.yaml"
SERVICE_PATH = Path(os.environ.get("MIHOMO_SERVICE", "/etc/systemd/system/mihomo.service"))

TUN_DEFAULT = {
    "enable": False,
    "stack": "system",
    "auto-route": True,
    "auto-detect-interface": True,
    "auto-redirect": True,
    "strict-route": False,
    "dns-hijack": ["any:53"],
    "inet4-route-exclude-address": [
        "192.168.0.0/16",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "127.0.0.0/8",
    ],
}


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\-]", "_", name.strip(), flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    return s or "provider"


class ConfigManager:
    def __init__(self, path: Path | None = None):
        self.path = path or CONFIG_PATH

    def load(self) -> dict[str, Any]:
        with open(self.path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def save(self, cfg: dict[str, Any]) -> str:
        backup = self.path.with_suffix(f".bak.{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(self.path, backup)
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        return str(backup)

    def validate(self) -> tuple[bool, str]:
        proc = subprocess.run(
            [MIHOMO_BIN, "-t", "-f", str(self.path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out.strip()

    def restart_service(self) -> tuple[bool, str]:
        proc = subprocess.run(
            ["systemctl", "restart", "mihomo"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out.strip()

    def service_status(self) -> str:
        proc = subprocess.run(
            ["systemctl", "is-active", "mihomo"],
            capture_output=True,
            text=True,
        )
        return (proc.stdout or proc.stderr or "unknown").strip()

    def get_mode(self) -> str:
        return self.load().get("mode", "rule")

    def set_mode(self, mode: str) -> str:
        if mode not in ("rule", "global", "direct"):
            raise ValueError("mode 必须是 rule / global / direct")
        cfg = self.load()
        cfg["mode"] = mode
        return self.save(cfg)

    def get_tun(self) -> dict[str, Any]:
        cfg = self.load()
        tun = cfg.get("tun") or {}
        return {**TUN_DEFAULT, **tun}

    def get_transparent_proxy(self) -> dict[str, Any]:
        """旁路由实际生效的透明代理方式（TUN / REDIR / TPROXY）。"""
        cfg = self.load()
        tun_on = bool((cfg.get("tun") or {}).get("enable"))
        redir = cfg.get("redir-port")
        tproxy = cfg.get("tproxy-port")
        parts: list[str] = []
        if tun_on:
            parts.append("TUN")
        if redir:
            parts.append(f"REDIR:{redir}")
        if tproxy:
            parts.append(f"TPROXY:{tproxy}")
        if parts:
            label = " · ".join(parts)
            short = "旁路由" if redir and not tun_on else label
        else:
            label = short = "未配置"
        return {
            "active": bool(parts),
            "label": label,
            "short": short,
            "tun_enable": tun_on,
            "redir_port": redir,
            "tproxy_port": tproxy,
        }

    def set_tun(self, enable: bool) -> str:
        cfg = self.load()
        tun = dict(TUN_DEFAULT)
        tun["enable"] = bool(enable)
        cfg["tun"] = tun
        backup = self.save(cfg)
        self._ensure_tun_service_caps(enable)
        if enable:
            subprocess.run(["sysctl", "-w", "net.ipv4.ip_forward=1"], capture_output=True, timeout=5)
            fwd = Path("/etc/sysctl.d/99-mihomo-forward.conf")
            if not fwd.exists():
                fwd.write_text("net.ipv4.ip_forward=1\n", encoding="utf-8")
        return backup

    def _ensure_tun_service_caps(self, enable: bool) -> None:
        if not SERVICE_PATH.exists():
            return
        text = SERVICE_PATH.read_text(encoding="utf-8")
        cap_lines = [
            "AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE",
            "CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE",
        ]
        if enable:
            for line in cap_lines:
                if line not in text:
                    text = text.replace("LimitNOFILE=1048576\n", f"LimitNOFILE=1048576\n{line}\n")
        else:
            for line in cap_lines:
                text = text.replace(line + "\n", "")
        SERVICE_PATH.write_text(text, encoding="utf-8")
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=10)

    def list_providers(self, *, mask_urls: bool = False) -> list[dict[str, Any]]:
        from subscription import provider_public_meta, type_label
        from utils import mask_url

        cfg = self.load()
        providers = cfg.get("proxy-providers") or {}
        result = []
        for name, spec in providers.items():
            url = spec.get("url", "")
            ptype = spec.get("type", "http")
            item = {
                "name": name,
                "type": ptype,
                "type_label": type_label(ptype),
                "url": mask_url(url) if mask_urls and url else url,
                "url_full": url if mask_urls else None,
                "interval": spec.get("interval", 3600),
                "path": spec.get("path", f"./providers/{name}.yaml"),
                "health_check": spec.get("health-check", {}),
                "has_inline": ptype == "inline",
                **provider_public_meta(spec),
            }
            result.append(item)
        return result

    def get_provider_url(self, name: str) -> str:
        cfg = self.load()
        providers = cfg.get("proxy-providers") or {}
        if name not in providers:
            raise ValueError(f"机场 {name} 不存在")
        spec = providers[name]
        if spec.get("type") != "http":
            raise ValueError("仅远程 HTTP 订阅支持复制链接/二维码")
        url = spec.get("url", "")
        if not url:
            raise ValueError("该机场未配置订阅 URL")
        return url

    def add_provider(
        self,
        name: str,
        url: str = "",
        *,
        provider_type: str = "http",
        path: str | None = None,
        payload: Any = None,
        interval: int = 3600,
        headers: Any = None,
        user_agent: str | None = None,
        exclude_filter: str | None = None,
        add_to_auto: bool = True,
        filter_regex: str | None = None,
    ) -> dict[str, Any]:
        from subscription import build_provider_spec

        cfg = self.load()
        key = _slug(name)
        if key in (cfg.get("proxy-providers") or {}):
            raise ValueError(f"机场 {key} 已存在")

        spec = build_provider_spec(
            provider_type,
            name_key=key,
            url=url,
            path=path,
            payload=payload,
            interval=interval,
            headers=headers,
            user_agent=user_agent,
            filter_regex=filter_regex,
            exclude_filter=exclude_filter,
        )
        providers = cfg.setdefault("proxy-providers", {})
        providers[key] = spec

        if add_to_auto:
            for group in cfg.get("proxy-groups") or []:
                if group.get("name") == "AUTO" and group.get("type") == "url-test":
                    uses = group.setdefault("use", [])
                    if key not in uses:
                        uses.append(key)
                    if filter_regex:
                        group["filter"] = filter_regex
                    break

        backup = self.save(cfg)
        return {"name": key, "backup": backup}

    def update_provider(
        self,
        name: str,
        url: str = "",
        interval: int | None = None,
        *,
        provider_type: str | None = None,
        path: str | None = None,
        payload: Any = None,
        headers: Any = None,
        user_agent: str | None = None,
    ) -> str:
        from subscription import build_provider_spec, normalize_provider_type

        cfg = self.load()
        providers = cfg.get("proxy-providers") or {}
        if name not in providers:
            raise ValueError(f"机场 {name} 不存在")
        old = providers[name]
        ptype = normalize_provider_type(provider_type or old.get("type", "http"))
        spec = build_provider_spec(
            ptype,
            name_key=name,
            url=url or old.get("url", ""),
            path=path or old.get("path"),
            payload=payload if payload is not None else old.get("payload"),
            interval=interval if interval is not None else old.get("interval", 3600),
            headers=headers if headers is not None else old.get("header"),
            user_agent=user_agent,
            filter_regex=old.get("filter"),
            exclude_filter=old.get("exclude-filter"),
        )
        providers[name] = spec
        return self.save(cfg)

    def remove_provider(self, name: str) -> str:
        cfg = self.load()
        providers = cfg.get("proxy-providers") or {}
        if name not in providers:
            raise ValueError(f"机场 {name} 不存在")
        del providers[name]
        for group in cfg.get("proxy-groups") or []:
            uses = group.get("use") or []
            if name in uses:
                group["use"] = [u for u in uses if u != name]
        provider_file = CONFIG_DIR / "providers" / f"{name}.yaml"
        if provider_file.exists():
            provider_file.unlink()
        return self.save(cfg)

    def get_rules(self) -> list[str]:
        cfg = self.load()
        return list(cfg.get("rules") or [])

    def set_rules(self, rules: list[str]) -> str:
        cfg = self.load()
        cleaned = [r.strip() for r in rules if r and r.strip()]
        if not cleaned:
            raise ValueError("规则不能为空")
        cfg["rules"] = cleaned
        return self.save(cfg)

    def get_groups(self) -> list[dict[str, Any]]:
        return list(self.load().get("proxy-groups") or [])

    def set_groups(self, groups: list[dict[str, Any]]) -> str:
        cfg = self.load()
        if not groups:
            raise ValueError("策略组不能为空")
        cfg["proxy-groups"] = groups
        return self.save(cfg)

    def apply(self) -> dict[str, Any]:
        ok, msg = self.validate()
        if not ok:
            return {"ok": False, "step": "validate", "message": msg}
        ok, msg = self.restart_service()
        if not ok:
            return {"ok": False, "step": "restart", "message": msg}
        return {"ok": True, "service": self.service_status(), "message": msg}

    def proxy_test(self) -> tuple[bool, str]:
        proc = subprocess.run(
            [
                "curl",
                "-x",
                "http://127.0.0.1:7890",
                "-I",
                "--connect-timeout",
                "10",
                "https://www.google.com",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0 and "HTTP/" in out, out.strip()

    def recent_logs(self, lines: int = 80) -> str:
        proc = subprocess.run(
            ["journalctl", "-u", "mihomo", "-n", str(lines), "--no-pager"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (proc.stdout or proc.stderr or "").strip()
