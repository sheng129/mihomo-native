from __future__ import annotations

from flask import Blueprint, jsonify, request

from auth import login_required
from autopilot import pick_dashboard_nodes, try_autopilot
from deps import DASHBOARD_NODE_LIMIT, cfg_mgr, mihomo
from panel_settings import get_settings
from traffic_store import traffic_report

bp = Blueprint("dashboard", __name__)


@bp.route("/api/dashboard")
@login_required
def api_dashboard():
    settings = get_settings()
    try:
        status = mihomo.status()
    except Exception as e:
        status = {"error": str(e)}
    traffic = traffic_report(
        status.get("providers_runtime") if isinstance(status, dict) else None,
        known_names={p["name"] for p in cfg_mgr.list_providers()},
    )
    proxy = None
    if request.args.get("test") == "1":
        ok, proxy_out = cfg_mgr.proxy_test()
        proxy = {"ok": ok, "output": proxy_out}
    tun = cfg_mgr.get_tun()
    transparent = cfg_mgr.get_transparent_proxy()
    auto_nodes = {"group": "AUTO", "now": "", "nodes": [], "display_nodes": []}
    try:
        raw = mihomo.auto_group_nodes("AUTO")
        raw["display_nodes"] = pick_dashboard_nodes(raw.get("nodes") or [])
        raw["display_limit"] = DASHBOARD_NODE_LIMIT
        raw["total_nodes"] = len(raw.get("nodes") or [])
        auto_nodes = raw
    except Exception:
        pass
    autopilot = {"ran": False, "reason": "skip"}
    if isinstance(status, dict) and auto_nodes.get("nodes"):
        try:
            autopilot = try_autopilot(
                auto_nodes=auto_nodes,
                traffic=traffic,
                providers_runtime=status.get("providers_runtime"),
                settings=settings,
            )
            if autopilot.get("switched"):
                raw2 = mihomo.auto_group_nodes("AUTO")
                raw2["display_nodes"] = pick_dashboard_nodes(raw2.get("nodes") or [])
                raw2["display_limit"] = DASHBOARD_NODE_LIMIT
                raw2["total_nodes"] = len(raw2.get("nodes") or [])
                auto_nodes = raw2
        except Exception as e:
            autopilot = {"ran": False, "reason": str(e)}
    return jsonify(
        {
            "service": cfg_mgr.service_status(),
            "mihomo": status,
            "proxy_test": proxy,
            "traffic": traffic,
            "mode": cfg_mgr.get_mode(),
            "tun": tun,
            "transparent_proxy": transparent,
            "auto_nodes": auto_nodes,
            "autopilot": autopilot,
        }
    )


@bp.route("/api/mode", methods=["GET", "POST"])
@login_required
def api_mode():
    if request.method == "GET":
        runtime = {}
        try:
            runtime = mihomo.get("/configs")
        except Exception:
            pass
        return jsonify({"config_mode": cfg_mgr.get_mode(), "runtime_mode": runtime.get("mode")})

    body = request.json or {}
    mode = body.get("mode", "").strip()
    if mode not in ("rule", "global", "direct"):
        return jsonify({"error": "mode 必须是 rule / global / direct"}), 400
    try:
        cfg_mgr.set_mode(mode)
        mihomo.patch("/configs", {"mode": mode})
        return jsonify({"ok": True, "mode": mode})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/tun", methods=["GET", "POST"])
@login_required
def api_tun():
    if request.method == "GET":
        return jsonify(cfg_mgr.get_tun())
    body = request.json or {}
    enable = bool(body.get("enable"))
    try:
        backup = cfg_mgr.set_tun(enable)
        apply_result = cfg_mgr.apply()
        return jsonify({"backup": backup, "tun": cfg_mgr.get_tun(), "apply": apply_result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/traffic")
@login_required
def api_traffic():
    runtime = {}
    try:
        runtime = mihomo.get("/providers/proxies")
    except Exception:
        pass
    return jsonify(
        traffic_report(
            runtime,
            known_names={p["name"] for p in cfg_mgr.list_providers()},
        )
    )


@bp.route("/api/traffic/quotas", methods=["GET", "PUT"])
@login_required
def api_quotas():
    from traffic_store import get_quotas, set_provider_quota

    if request.method == "GET":
        return jsonify(get_quotas())
    body = request.json or {}
    name = body.get("name", "").strip()
    if not name:
        return jsonify({"error": "name 必填"}), 400
    limit = body.get("limit_gb")
    alert = int(body.get("alert_percent", 80))
    data = set_provider_quota(name, float(limit) if limit not in (None, "", 0) else None, alert)
    return jsonify(data)


@bp.route("/api/proxy-test", methods=["POST"])
@login_required
def api_proxy_test():
    ok, proxy_out = cfg_mgr.proxy_test()
    return jsonify({"ok": ok, "output": proxy_out})


@bp.route("/api/connections")
@login_required
def api_connections():
    return jsonify(mihomo.get("/connections"))
