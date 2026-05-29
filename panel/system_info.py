"""读取 N1 / Armbian 等 Linux 主机系统信息"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any


def _read_os_release() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
        except OSError:
            pass
        break
    return out


def _read_armbian() -> dict[str, str]:
    out: dict[str, str] = {}
    path = Path("/etc/armbian-release")
    if not path.exists():
        return out
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    except OSError:
        pass
    return out


def _uptime_human() -> tuple[int, str]:
    try:
        with open("/proc/uptime", encoding="utf-8") as f:
            sec = int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return 0, ""
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d} 天")
    if h:
        parts.append(f"{h} 小时")
    if m or not parts:
        parts.append(f"{m} 分")
    return sec, "".join(parts)


def _memory_summary() -> str:
    try:
        mem: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        if not total:
            return ""
        used = max(0, total - avail)
        return f"{used // 1024} / {total // 1024} MB"
    except (OSError, ValueError):
        return ""


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.lower().startswith(("model name", "hardware", "processor")):
                    _, _, val = line.partition(":")
                    val = val.strip()
                    if val and val not in ("0", "AArch64 Processor"):
                        return val
    except OSError:
        pass
    return platform.processor() or ""


def _disk_root() -> str:
    try:
        proc = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=3)
        if proc.returncode == 0:
            lines = [ln.split() for ln in proc.stdout.strip().splitlines() if ln.strip()]
            if len(lines) >= 2 and len(lines[-1]) >= 5:
                p = lines[-1]
                return f"{p[2]} / {p[1]}（{p[4]}）"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def get_system_info() -> dict[str, Any]:
    os_release = _read_os_release()
    armbian = _read_armbian()
    uname = platform.uname()
    uptime_sec, uptime_human = _uptime_human()

    os_name = os_release.get("NAME") or os_release.get("ID") or ""
    os_version = os_release.get("VERSION_ID") or armbian.get("VERSION") or ""
    os_pretty = os_release.get("PRETTY_NAME") or os_name
    if os_version and os_version not in os_pretty:
        os_pretty = f"{os_pretty} {os_version}".strip()

    board = armbian.get("BOARD") or armbian.get("BOARD_NAME") or ""
    if not board:
        try:
            dt = Path("/proc/device-tree/model")
            if dt.exists():
                board = dt.read_bytes().decode("utf-8", errors="replace").strip("\x00")
        except OSError:
            pass

    arch = uname.machine or platform.machine() or ""
    arch_label = arch
    if arch in ("aarch64", "arm64"):
        arch_label = "ARM64 (aarch64)"
    elif arch.startswith("arm"):
        arch_label = f"ARM ({arch})"

    return {
        "os_name": os_name,
        "os_pretty": os_pretty,
        "os_version": os_version,
        "os_id": os_release.get("ID", ""),
        "architecture": arch,
        "architecture_label": arch_label,
        "kernel": uname.release or "",
        "hostname": uname.node or "",
        "board": board,
        "cpu_model": _cpu_model(),
        "memory": _memory_summary(),
        "disk_root": _disk_root(),
        "uptime_sec": uptime_sec,
        "uptime_human": uptime_human,
        "is_armbian": bool(armbian) or (os_release.get("ID", "").lower() == "armbian"),
    }
