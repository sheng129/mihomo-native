"""面板共享依赖（配置、mihomo 客户端、常量）。"""
from __future__ import annotations

import os
from pathlib import Path

from config_manager import ConfigManager
from mihomo_api import MihomoAPI

APP_DIR = Path(__file__).resolve().parent
DASHBOARD_NODE_LIMIT = 4
MIHOMO_API = os.environ.get("MIHOMO_API", "http://127.0.0.1:9090")
MIHOMO_SECRET = os.environ.get("MIHOMO_SECRET", "")
RUNTIME_STATE = Path(os.environ.get("PANEL_RUNTIME_STATE", "/var/lib/n1-panel/runtime_state.json"))

cfg_mgr = ConfigManager()
mihomo = MihomoAPI(MIHOMO_API, MIHOMO_SECRET)
