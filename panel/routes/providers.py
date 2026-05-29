from __future__ import annotations

import io

import segno
from flask import Blueprint, Response, jsonify, request

from auth import login_required
from deps import cfg_mgr, mihomo
from subscription import (
    SUBSCRIPTION_PRESETS,
    detect_provider_type_from_url,
    list_provider_types,
)
from traffic_store import set_provider_quota

bp = Blueprint("providers", __name__)


@bp.route("/api/providers/types")
@login_required
def api_providers_types():
    return jsonify({
        "types": list_provider_types(),
        "presets": SUBSCRIPTION_PRESETS,
    })


@bp.route("/api/providers", methods=["GET"])
@login_required
def api_providers_list():
    runtime = {}
    try:
        runtime = mihomo.get("/providers/proxies")
    except Exception:
        pass
    providers = cfg_mgr.list_providers(mask_urls=True)
    for p in providers:
        rt = runtime.get("providers", {}).get(p["name"], {})
        p["subscription_info"] = rt.get("subscriptionInfo")
        p["vehicle_type"] = rt.get("vehicleType")
        p["updated_at"] = rt.get("updatedAt")
    return jsonify({"providers": providers})


@bp.route("/api/providers", methods=["POST"])
@login_required
def api_providers_add():
    body = request.json or {}
    name = body.get("name", "").strip()
    url = (body.get("url") or "").strip()
    provider_type = body.get("provider_type") or detect_provider_type_from_url(url)
    path = (body.get("path") or "").strip() or None
    payload = body.get("payload")
    if not name:
        return jsonify({"error": "名称必填"}), 400
    if provider_type == "http" and not url:
        return jsonify({"error": "远程订阅必须填写 URL"}), 400
    if provider_type == "file" and not path and not url:
        return jsonify({"error": "本地文件必须填写 path"}), 400
    if provider_type == "inline" and not payload:
        return jsonify({"error": "内联节点必须填写节点内容"}), 400
    try:
        result = cfg_mgr.add_provider(
            name,
            url,
            provider_type=provider_type,
            path=path,
            payload=payload,
            interval=int(body.get("interval", 3600)),
            headers=body.get("headers"),
            user_agent=(body.get("user_agent") or "").strip() or None,
            exclude_filter=body.get("exclude_filter") or None,
            add_to_auto=body.get("add_to_auto", True),
            filter_regex=body.get("filter") or None,
        )
        limit_gb = body.get("limit_gb")
        if limit_gb not in (None, "", 0):
            set_provider_quota(result["name"], float(limit_gb))
        apply_result = cfg_mgr.apply()
        return jsonify({"provider": result, "apply": apply_result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/providers/<name>", methods=["PUT"])
@login_required
def api_providers_update(name):
    body = request.json or {}
    url = (body.get("url") or "").strip()
    try:
        backup = cfg_mgr.update_provider(
            name,
            url,
            body.get("interval"),
            provider_type=body.get("provider_type"),
            path=(body.get("path") or "").strip() or None,
            payload=body.get("payload"),
            headers=body.get("headers"),
            user_agent=(body.get("user_agent") or "").strip() or None,
        )
        apply_result = cfg_mgr.apply()
        return jsonify({"backup": backup, "apply": apply_result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/api/providers/<name>", methods=["DELETE"])
@login_required
def api_providers_delete(name):
    try:
        backup = cfg_mgr.remove_provider(name)
        apply_result = cfg_mgr.apply()
        return jsonify({"backup": backup, "apply": apply_result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/api/providers/<name>/url")
@login_required
def api_provider_url(name):
    try:
        return jsonify({"url": cfg_mgr.get_provider_url(name)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@bp.route("/api/providers/<name>/qr")
@login_required
def api_provider_qr(name):
    try:
        url = cfg_mgr.get_provider_url(name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    qr = segno.make(url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=5, border=2)
    return Response(buf.getvalue(), mimetype="image/png")


@bp.route("/api/providers/<name>/refresh", methods=["POST"])
@login_required
def api_providers_refresh(name):
    try:
        mihomo.put(f"/providers/proxies/{name}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
