"""登录与会话。"""
from __future__ import annotations

import functools
import os

from flask import jsonify, redirect, request, session, url_for


def panel_password() -> str:
    return os.environ.get("PANEL_PASSWORD", "n1admin")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("auth"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "未登录"}), 401
            return redirect(url_for("auth.login_page"))
        return view(*args, **kwargs)

    return wrapped
