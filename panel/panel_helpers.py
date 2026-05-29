"""通用工具：本机 IP、机场节点映射。"""
from __future__ import annotations

import os
import socket
import subprocess


def local_ip() -> str:
    lan_if = os.environ.get("LAN_IF", "eth0")
    try:
        proc = subprocess.run(
            ["ip", "-4", "addr", "show", "dev", lan_if],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0:
            for line in (proc.stdout or "").splitlines():
                line = line.strip()
                if line.startswith("inet "):
                    return line.split()[1].split("/")[0]
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def provider_nodes(providers_runtime: dict | None) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    providers = ((providers_runtime or {}).get("providers") or {}) if isinstance(providers_runtime, dict) else {}
    for name, row in providers.items():
        nodes: set[str] = set()
        for p in row.get("proxies") or []:
            if isinstance(p, dict) and p.get("name"):
                nodes.add(str(p["name"]))
            elif isinstance(p, str):
                nodes.add(p)
        out[name] = nodes
    return out


def node_to_provider_map(providers_runtime: dict | None) -> dict[str, str]:
    m: dict[str, str] = {}
    for pname, nodes in provider_nodes(providers_runtime).items():
        for n in nodes:
            m[n] = pname
    return m
