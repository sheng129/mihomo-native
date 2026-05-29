from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

from auth import login_required, panel_password
from deps import mihomo
from panel_helpers import local_ip
from panel_settings import change_password, get_settings, restart_panel, save_settings
from system_info import get_system_info

bp = Blueprint("settings_api", __name__)


@bp.route("/api/settings", methods=["GET", "PUT"])
@login_required
def api_settings():
    if request.method == "GET":
        data = get_settings()
        data["local_ip"] = local_ip()
        data["panel_port"] = int(os.environ.get("PANEL_PORT", "8088"))
        try:
            version = mihomo.get("/version", timeout=3)
            data["mihomo_version"] = version.get("version") if isinstance(version, dict) else str(version)
        except Exception:
            data["mihomo_version"] = ""
        try:
            data["system"] = get_system_info()
        except Exception:
            data["system"] = {}
        return jsonify(data)
    body = request.json or {}
    try:
        return jsonify(save_settings(body))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/api/settings/password", methods=["POST"])
@login_required
def api_settings_password():
    body = request.json or {}
    old_p = body.get("old_password", "")
    new_p = body.get("new_password", "")
    confirm = body.get("confirm_password", "")
    if new_p != confirm:
        return jsonify({"error": "两次新密码不一致"}), 400
    try:
        change_password(old_p, new_p, panel_password())
        ok, msg = restart_panel()
        return jsonify({"ok": True, "restarted": ok, "message": msg or "密码已更新，请重新登录"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
