from __future__ import annotations

from flask import Blueprint, jsonify, request

from auth import login_required
from deps import cfg_mgr, mihomo

bp = Blueprint("config_api", __name__)


@bp.route("/api/rules", methods=["GET"])
@login_required
def api_rules_get():
    return jsonify({"rules": cfg_mgr.get_rules()})


@bp.route("/api/rules", methods=["PUT"])
@login_required
def api_rules_set():
    body = request.json or {}
    rules = body.get("rules")
    if not isinstance(rules, list):
        return jsonify({"error": "rules 必须是数组"}), 400
    try:
        backup = cfg_mgr.set_rules(rules)
        apply_result = cfg_mgr.apply()
        return jsonify({"backup": backup, "apply": apply_result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/api/groups", methods=["GET"])
@login_required
def api_groups_get():
    return jsonify({"groups": cfg_mgr.get_groups()})


@bp.route("/api/groups", methods=["PUT"])
@login_required
def api_groups_set():
    body = request.json or {}
    groups = body.get("groups")
    if not isinstance(groups, list):
        return jsonify({"error": "groups 必须是数组"}), 400
    try:
        backup = cfg_mgr.set_groups(groups)
        apply_result = cfg_mgr.apply()
        return jsonify({"backup": backup, "apply": apply_result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/api/runtime", methods=["PATCH"])
@login_required
def api_runtime():
    body = request.json or {}
    allowed = {k: v for k, v in body.items() if k in ("mode", "log-level") and v}
    if not allowed:
        return jsonify({"error": "仅支持 mode / log-level"}), 400
    try:
        mihomo.patch("/configs", allowed)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/config/validate", methods=["POST"])
@login_required
def api_validate():
    ok, msg = cfg_mgr.validate()
    return jsonify({"ok": ok, "message": msg})


@bp.route("/api/config/apply", methods=["POST"])
@login_required
def api_apply():
    return jsonify(cfg_mgr.apply())


@bp.route("/api/service/restart", methods=["POST"])
@login_required
def api_restart():
    ok, msg = cfg_mgr.restart_service()
    return jsonify({"ok": ok, "service": cfg_mgr.service_status(), "message": msg})


@bp.route("/api/logs")
@login_required
def api_logs():
    lines = int(request.args.get("lines", 80))
    return jsonify({"logs": cfg_mgr.recent_logs(lines)})
