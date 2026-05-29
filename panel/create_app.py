"""Flask 应用工厂。"""
from __future__ import annotations

import os
import secrets

from flask import Flask

from deps import APP_DIR
from routes import register_routes


def create_app() -> Flask:
    secret = os.environ.get("PANEL_SECRET") or secrets.token_hex(16)
    app = Flask(
        __name__,
        template_folder=str(APP_DIR / "templates"),
        static_folder=str(APP_DIR / "static"),
    )
    app.secret_key = secret
    register_routes(app)
    return app
