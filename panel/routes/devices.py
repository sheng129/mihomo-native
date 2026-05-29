from __future__ import annotations

from flask import Blueprint, jsonify, request

from auth import login_required
from deps import mihomo
from device_manager import (
    apply_policies,
    batch_update_devices,
    delete_device,
    list_devices,
    update_device,
)

bp = Blueprint("devices", __name__)


@bp.route("/api/devices")
@login_required
def api_devices_list():
    try:
        conns = mihomo.get("/connections", timeout=5)
    except Exception:
        conns = {}
    data = list_devices(conns)
    if data.get("mac_synced"):
        try:
            apply_policies()
        except Exception:
            pass
    return jsonify(data)


@bp.route("/api/devices/<path:device_id>", methods=["PUT", "DELETE"])
@login_required
def api_devices_one(device_id):
    if request.method == "DELETE":
        try:
            delete_device(device_id)
            return jsonify({"ok": True})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    body = request.json or {}
    try:
        row = update_device(
            device_id,
            policy=body.get("policy"),
            alias=body.get("alias"),
            note=body.get("note"),
            mac=body.get("mac"),
            hostname=body.get("hostname"),
            device_type=body.get("device_type"),
            os_name=body.get("os"),
        )
        return jsonify({"ok": True, "device": row})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/api/devices/batch", methods=["POST"])
@login_required
def api_devices_batch():
    body = request.json or {}
    macs = body.get("macs") or body.get("ips") or []
    if not isinstance(macs, list):
        return jsonify({"error": "macs 必须是数组"}), 400
    try:
        result = batch_update_devices(macs, body.get("policy", ""))
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/api/devices/apply", methods=["POST"])
@login_required
def api_devices_apply():
    return jsonify(apply_policies())
