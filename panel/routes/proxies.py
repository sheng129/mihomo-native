from __future__ import annotations

import time
import urllib.parse

from flask import Blueprint, jsonify, request

from auth import login_required
from autopilot import pick_dashboard_nodes
from deps import mihomo
from panel_settings import get_settings
from runtime_state import load_runtime_state, save_runtime_state

bp = Blueprint("proxies", __name__)


@bp.route("/api/proxies")
@login_required
def api_proxies():
    data = mihomo.get("/proxies")
    auto = data.get("proxies", {}).get("AUTO", {})
    nodes = []
    for name, info in data.get("proxies", {}).items():
        if info.get("type") in ("Shadowsocks", "Vmess", "Vless", "Trojan", "Hysteria2", "Hysteria"):
            nodes.append(
                {
                    "name": name,
                    "type": info.get("type"),
                    "alive": info.get("alive"),
                    "history": info.get("history", [])[-1:] if info.get("history") else [],
                }
            )
    return jsonify({"auto": auto, "nodes": nodes, "total": len(nodes)})


@bp.route("/api/proxies/delay", methods=["POST"])
@login_required
def api_delay():
    group = (request.json or {}).get("group", "AUTO")
    timeout = int((request.json or {}).get("timeout", 8000))
    try:
        delays = mihomo.delay_test(group, timeout)
        return jsonify({"ok": True, "delays": delays})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/proxies/auto")
@login_required
def api_proxies_auto():
    group = request.args.get("group", "AUTO")
    refresh = request.args.get("refresh") == "1"
    limit = min(max(int(request.args.get("limit", 6)), 1), 20)
    try:
        data = mihomo.auto_group_nodes(group)
        display = pick_dashboard_nodes(data["nodes"], limit)
        if refresh:
            state = load_runtime_state()
            cooldown = int(get_settings().get("node_test_cooldown_sec", 600))
            last = float(state.get("last_node_test_ts", 0))
            if time.time() - last < cooldown:
                data["cooldown_left"] = int(cooldown - (time.time() - last))
                data["delay_tested"] = 0
                data["display_nodes"] = display
                data["display_limit"] = limit
                data["total_nodes"] = len(data["nodes"])
                return jsonify(data)
            tested = 0
            for n in display:
                try:
                    d = mihomo.proxy_delay(n["name"], 5000)
                    if d:
                        n["delay"] = d
                        tested += 1
                except Exception:
                    pass
            display.sort(
                key=lambda x: (
                    1 if not x.get("delay") or x["delay"] <= 0 else 0,
                    x.get("delay") or 99999,
                )
            )
            data["delay_tested"] = tested
            state["last_node_test_ts"] = time.time()
            save_runtime_state(state)
        data["display_nodes"] = display
        data["display_limit"] = limit
        data["total_nodes"] = len(data["nodes"])
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/proxies/select", methods=["POST"])
@login_required
def api_proxies_select():
    body = request.json or {}
    name = (body.get("name") or "").strip()
    group = (body.get("group") or "AUTO").strip()
    if not name:
        return jsonify({"error": "name 必填"}), 400
    try:
        mihomo.select_proxy(group, name)
        auto = mihomo.get(f"/proxies/{urllib.parse.quote(group, safe='')}", timeout=5)
        now = auto.get("now", name) if isinstance(auto, dict) else name
        return jsonify({"ok": True, "group": group, "now": now, "name": name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
