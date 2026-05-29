"""局域网设备发现与按 MAC 登记翻墙策略（iptables）"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
from datetime import datetime
import ipaddress
from pathlib import Path
from typing import Any

DEVICES_PATH = Path(os.environ.get("PANEL_DEVICES_PATH", "/var/lib/n1-panel/devices.json"))
LAN_IF = os.environ.get("LAN_IF", "eth0")
LAN_NET = os.environ.get("LAN_NET", "192.168.5.0/24")
N1_IP = os.environ.get("N1_IP", "192.168.5.7")
DEV_CHAIN = "MIHOMO_DEV"

VALID_POLICIES = ("proxy", "direct", "block")
NEW_DEVICE_POLICIES = ("proxy", "direct")
_MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$", re.I)


def default_device_policy() -> str:
    try:
        from panel_settings import get_settings

        p = get_settings().get("default_device_policy", "direct")
        return p if p in NEW_DEVICE_POLICIES else "direct"
    except Exception:
        return "direct"


def _load_db() -> dict[str, Any]:
    if not DEVICES_PATH.exists():
        return {"devices_by_mac": {}}
    try:
        data = json.loads(DEVICES_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _migrate_db(data)
            if isinstance(data.get("devices_by_mac"), dict):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"devices_by_mac": {}}


def _save_db(data: dict[str, Any]) -> None:
    DEVICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEVICES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _valid_ip(ip: str) -> bool:
    return bool(re.match(r"^(\d{1,3}\.){3}\d{1,3}$", ip))


def _normalize_mac(mac: str) -> str:
    m = (mac or "").strip().lower()
    if not m:
        return ""
    if "-" in m:
        m = m.replace("-", ":")
    if len(m) == 12 and ":" not in m:
        m = ":".join(m[i : i + 2] for i in range(0, 12, 2))
    return m if _MAC_RE.match(m) else ""


def _valid_mac(mac: str) -> bool:
    return bool(_normalize_mac(mac))


def _migrate_db(db: dict[str, Any]) -> None:
    """将旧版按 IP 存储的配置迁移为按 MAC。"""
    if db.get("devices_by_mac") and not db.get("devices"):
        return
    by_mac: dict[str, Any] = dict(db.get("devices_by_mac") or {})
    legacy = db.get("devices") or {}
    if not isinstance(legacy, dict):
        legacy = {}
    changed = False
    for key, cfg in legacy.items():
        if not isinstance(cfg, dict):
            continue
        mac = _normalize_mac(str(cfg.get("mac") or ""))
        if not mac:
            continue
        last_ip = key if _valid_ip(key) else str(cfg.get("ip") or cfg.get("last_ip") or "")
        row = by_mac.setdefault(mac, {"mac": mac, "policy": default_device_policy()})
        for field in ("policy", "alias", "note", "hostname", "device_type", "os", "last_seen", "updated_at"):
            if cfg.get(field) not in (None, "") and not row.get(field):
                row[field] = cfg[field]
        if cfg.get("policy"):
            row["policy"] = cfg["policy"]
        if last_ip:
            row["last_ip"] = last_ip
        changed = True
    if legacy:
        db.pop("devices", None)
        changed = True
    if changed or "devices_by_mac" not in db:
        db["devices_by_mac"] = by_mac
        if changed:
            _save_db(db)


def _registry(db: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    data = db if db is not None else _load_db()
    reg = data.setdefault("devices_by_mac", {})
    if not isinstance(reg, dict):
        reg = {}
        data["devices_by_mac"] = reg
    return reg


def _mac_row(reg: dict[str, dict[str, Any]], mac: str, *, ip: str = "") -> dict[str, Any]:
    mac = _normalize_mac(mac)
    row = reg.setdefault(mac, {"mac": mac, "policy": default_device_policy()})
    row["mac"] = mac
    if ip:
        row["last_ip"] = ip
        row["last_seen"] = datetime.now().isoformat(timespec="seconds")
    return row


def _resolve_mac(device_id: str, reg: dict[str, dict[str, Any]] | None = None) -> str:
    """从 MAC 或当前 ARP 表中的 IP 解析出标准 MAC。"""
    mac = _normalize_mac(device_id)
    if mac:
        return mac
    if not _valid_ip(device_id) or device_id == N1_IP:
        return ""
    reg = reg or _registry()
    for m, cfg in reg.items():
        if cfg.get("last_ip") == device_id:
            return m
    for n in _neighbors():
        if n.get("ip") == device_id:
            return _normalize_mac(n.get("mac") or "")
    return ""


def _is_lan_ipv4(ip: str) -> bool:
    try:
        obj = ipaddress.ip_address(ip)
        return obj.version == 4 and obj.is_private
    except ValueError:
        return False


def _reverse_name(ip: str) -> str:
    try:
        name, _, _ = socket.gethostbyaddr(ip)
        return name.split(".")[0]
    except OSError:
        return ""


def _guess_device(hostname: str, hosts: list[str]) -> tuple[str, str]:
    text = f"{hostname} {' '.join(hosts)}".lower()
    if any(k in text for k in ("iphone", "ipad", "ios", "apple")):
        return "手机/平板", "iOS"
    if any(k in text for k in ("android", "miui", "huawei", "honor", "oppo", "vivo", "xiaomi")):
        return "手机", "Android"
    if any(k in text for k in ("windows", "win-", "desktop", "laptop", "pc")):
        return "电脑", "Windows"
    if any(k in text for k in ("macbook", "imac", "macos")):
        return "电脑", "macOS"
    if any(k in text for k in ("ubuntu", "debian", "centos", "linux")):
        return "电脑/服务器", "Linux"
    if any(k in text for k in ("tv", "iptv", "xiaomi-tv")):
        return "电视", "Unknown"
    if any(k in text for k in ("printer", "hp-", "epson", "canon")):
        return "打印机", "Unknown"
    return "未知设备", "Unknown"


def _neighbors() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    try:
        proc = subprocess.run(
            ["ip", "-j", "neigh", "show", "dev", LAN_IF],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            for row in json.loads(proc.stdout):
                ip = row.get("dst")
                if not ip or ip == N1_IP or not _valid_ip(ip) or not _is_lan_ipv4(ip):
                    continue
                mac = _normalize_mac(row.get("lladdr") or "")
                state = row.get("state") or ""
                if state in ("FAILED", "INCOMPLETE"):
                    continue
                items.append({"ip": ip, "mac": mac, "source": "neigh"})
    except (json.JSONDecodeError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    if not items:
        proc = subprocess.run(
            ["ip", "neigh", "show", "dev", LAN_IF],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in (proc.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            ip = parts[0]
            if not _valid_ip(ip) or ip == N1_IP or not _is_lan_ipv4(ip):
                continue
            mac = _normalize_mac(parts[4] if parts[3] == "lladdr" else "")
            items.append({"ip": ip, "mac": mac, "source": "neigh"})
    return items


def _connection_sources(conns: list[dict]) -> dict[str, dict[str, Any]]:
    by_ip: dict[str, dict[str, Any]] = {}
    for c in conns:
        meta = c.get("metadata") or {}
        ip = meta.get("sourceIP") or meta.get("sourceIp") or meta.get("source")
        if not ip or not _valid_ip(str(ip)) or not _is_lan_ipv4(str(ip)):
            continue
        ip = str(ip)
        entry = by_ip.setdefault(ip, {"conn_count": 0, "hosts": set()})
        entry["conn_count"] += 1
        host = meta.get("host") or meta.get("destinationIP") or ""
        if host:
            entry["hosts"].add(str(host))
    for v in by_ip.values():
        v["hosts"] = sorted(v["hosts"])[:8]
    return by_ip


def _build_live_ip_mac() -> dict[str, str]:
    """当前在线 IP → MAC。"""
    ip_mac: dict[str, str] = {}
    for n in _neighbors():
        ip, mac = n["ip"], n.get("mac") or ""
        if mac:
            ip_mac[ip] = mac
    return ip_mac


def list_devices(connections_payload: dict | None = None) -> dict[str, Any]:
    db = _load_db()
    reg = _registry(db)
    merged: dict[str, dict[str, Any]] = {}
    changed = False
    default_p = default_device_policy()
    ip_mac = _build_live_ip_mac()

    conns = []
    if isinstance(connections_payload, dict):
        conns = connections_payload.get("connections") or []
    conn_by_ip = _connection_sources(conns)

    def attach_live(ip: str, mac: str, *, online: bool) -> dict[str, Any]:
        nonlocal changed
        if not mac:
            return {}
        cfg = _mac_row(reg, mac, ip=ip if online else "")
        policy = cfg.get("policy") or default_p
        info = conn_by_ip.get(ip, {})
        hosts = info.get("hosts") or []
        hostname = cfg.get("hostname") or _reverse_name(ip) if ip else cfg.get("hostname", "")
        dtype, os_name = _guess_device(hostname, hosts)
        if online and ip:
            if cfg.get("last_ip") != ip:
                cfg["last_ip"] = ip
                changed = True
            cfg["last_seen"] = datetime.now().isoformat(timespec="seconds")
        row = {
            "device_key": mac,
            "mac": mac,
            "ip": ip or cfg.get("last_ip") or "",
            "alias": cfg.get("alias", ""),
            "policy": policy,
            "online": online,
            "conn_count": info.get("conn_count", 0) if online else 0,
            "hosts": hosts if online else [],
            "hostname": hostname,
            "device_type": cfg.get("device_type") or dtype,
            "os": cfg.get("os") or os_name,
            "last_seen": cfg.get("last_seen", ""),
            "note": cfg.get("note", ""),
            "policy_by_mac": True,
        }
        if not cfg.get("device_type") and dtype:
            cfg["device_type"] = dtype
            changed = True
        if not cfg.get("os") and os_name:
            cfg["os"] = os_name
            changed = True
        if mac not in reg or reg[mac].get("policy") != policy:
            cfg["policy"] = policy
        merged[mac] = row
        return row

    for ip, mac in ip_mac.items():
        if mac not in reg:
            _mac_row(reg, mac, ip=ip)
            reg[mac]["policy"] = default_p
            changed = True
        attach_live(ip, mac, online=True)

    for ip, info in conn_by_ip.items():
        mac = ip_mac.get(ip, "")
        if mac and mac in merged:
            merged[mac]["conn_count"] = info["conn_count"]
            merged[mac]["hosts"] = info["hosts"]
            merged[mac]["online"] = True
        elif not mac:
            merged[f"ip:{ip}"] = {
                "device_key": f"ip:{ip}",
                "mac": "",
                "ip": ip,
                "alias": "",
                "policy": default_p,
                "online": True,
                "conn_count": info["conn_count"],
                "hosts": info["hosts"],
                "hostname": _reverse_name(ip),
                "device_type": "",
                "os": "",
                "last_seen": datetime.now().isoformat(timespec="seconds"),
                "note": "",
                "policy_by_mac": False,
            }

    for mac, cfg in reg.items():
        if mac in merged:
            continue
        last_ip = cfg.get("last_ip") or ""
        merged[mac] = {
            "device_key": mac,
            "mac": mac,
            "ip": last_ip,
            "alias": cfg.get("alias", ""),
            "policy": cfg.get("policy", default_p),
            "online": last_ip in ip_mac and ip_mac.get(last_ip) == mac,
            "conn_count": 0,
            "hosts": [],
            "hostname": cfg.get("hostname", ""),
            "device_type": cfg.get("device_type", ""),
            "os": cfg.get("os", ""),
            "last_seen": cfg.get("last_seen", ""),
            "note": cfg.get("note", ""),
            "policy_by_mac": True,
        }

    devices = sorted(
        merged.values(),
        key=lambda x: (
            not x.get("online"),
            not x.get("mac"),
            int(ipaddress.ip_address(x.get("ip") or "0.0.0.0")),
        ),
    )
    if changed:
        _save_db(db)
        apply_policies()
    return {
        "devices": devices,
        "lan_if": LAN_IF,
        "lan_net": LAN_NET,
        "total": len(devices),
        "online": sum(1 for d in devices if d.get("online")),
        "mac_synced": changed,
        "default_device_policy": default_p,
        "policy_key": "mac",
    }


def batch_update_devices(device_ids: list[str], policy: str) -> dict[str, Any]:
    if policy not in VALID_POLICIES:
        raise ValueError("policy 必须是 proxy / direct / block")
    if not device_ids:
        raise ValueError("请至少选择一台设备")
    db = _load_db()
    reg = _registry(db)
    updated: list[str] = []
    skipped: list[str] = []
    for raw in device_ids:
        raw = str(raw).strip()
        mac = _resolve_mac(raw, reg) or _normalize_mac(raw)
        if not mac:
            skipped.append(raw)
            continue
        row = _mac_row(reg, mac)
        row["policy"] = policy
        row["updated_at"] = datetime.now().isoformat(timespec="seconds")
        updated.append(mac)
    if not updated:
        raise ValueError("没有可更新的有效 MAC（请刷新设备列表）")
    _save_db(db)
    apply_result = apply_policies()
    return {
        "updated": updated,
        "skipped": skipped,
        "policy": policy,
        "apply": apply_result,
    }


def update_device(
    device_id: str,
    *,
    policy: str | None = None,
    alias: str | None = None,
    note: str | None = None,
    mac: str | None = None,
    hostname: str | None = None,
    device_type: str | None = None,
    os_name: str | None = None,
) -> dict[str, Any]:
    db = _load_db()
    reg = _registry(db)
    resolved = _resolve_mac(device_id, reg) or _normalize_mac(mac or device_id)
    if not resolved:
        raise ValueError("需要有效 MAC 地址才能登记策略（请刷新设备列表）")
    if policy is not None and policy not in VALID_POLICIES:
        raise ValueError("policy 必须是 proxy / direct / block")
    row = _mac_row(reg, resolved)
    if policy is not None:
        row["policy"] = policy
    if alias is not None:
        row["alias"] = alias.strip()[:64]
    if note is not None:
        row["note"] = note.strip()[:200]
    if mac is not None:
        nm = _normalize_mac(mac)
        if nm and nm != resolved:
            raise ValueError("MAC 与设备不匹配")
    if hostname is not None:
        row["hostname"] = hostname.strip()[:64]
    if device_type is not None:
        row["device_type"] = device_type.strip()[:64]
    if os_name is not None:
        row["os"] = os_name.strip()[:64]
    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save_db(db)
    apply_policies()
    return row


def delete_device(device_id: str) -> None:
    db = _load_db()
    reg = _registry(db)
    mac = _resolve_mac(device_id, reg) or _normalize_mac(device_id)
    if not mac:
        raise ValueError("无效设备")
    reg.pop(mac, None)
    _save_db(db)
    apply_policies()


def apply_policies() -> dict[str, Any]:
    db = _load_db()
    reg = _registry(db)
    direct_macs: list[str] = []
    block_macs: list[str] = []
    errors: list[str] = []

    def run(cmd: list[str]) -> None:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        err = (proc.stderr or "").lower()
        if proc.returncode != 0 and proc.stderr and "exists" not in err:
            errors.append(proc.stderr.strip()[:120])

    for mac, cfg in reg.items():
        if not _valid_mac(mac):
            continue
        pol = cfg.get("policy")
        if pol == "direct":
            direct_macs.append(mac)
        elif pol == "block":
            block_macs.append(mac)

    run(["iptables", "-t", "nat", "-N", DEV_CHAIN])
    run(["iptables", "-t", "nat", "-F", DEV_CHAIN])
    run(["iptables", "-t", "nat", "-D", "MIHOMO_LAN", "-j", DEV_CHAIN])
    run(["iptables", "-t", "nat", "-I", "MIHOMO_LAN", "1", "-j", DEV_CHAIN])

    for mac in direct_macs:
        run(["iptables", "-t", "nat", "-A", DEV_CHAIN, "-m", "mac", "--mac-source", mac, "-j", "RETURN"])

    prev_block = db.get("_applied_block_mac") or []
    for mac in prev_block:
        run(["iptables", "-D", "FORWARD", "-m", "mac", "--mac-source", mac, "-j", "DROP"])
    for mac in block_macs:
        run(["iptables", "-I", "FORWARD", "1", "-m", "mac", "--mac-source", mac, "-j", "DROP"])
    db["_applied_block_mac"] = block_macs

    # 清理旧版按 IP 阻断规则
    for ip in db.get("_applied_block") or []:
        run(["iptables", "-D", "FORWARD", "-s", ip, "-j", "DROP"])
    db["_applied_block"] = []

    _save_db(db)
    return {
        "ok": len(errors) == 0,
        "direct_mac": direct_macs,
        "block_mac": block_macs,
        "errors": errors[:5],
    }
