"""HTTP 路由蓝图注册。"""
from __future__ import annotations

from flask import Flask

from routes.auth import bp as auth_bp
from routes.config_api import bp as config_bp
from routes.dashboard import bp as dashboard_bp
from routes.devices import bp as devices_bp
from routes.proxies import bp as proxies_bp
from routes.providers import bp as providers_bp
from routes.settings_api import bp as settings_bp


def register_routes(app: Flask) -> None:
    for bp in (auth_bp, dashboard_bp, proxies_bp, providers_bp, config_bp, settings_bp, devices_bp):
        app.register_blueprint(bp)
