#!/usr/bin/env python3
"""N1 Mihomo Web 管理面板入口。"""
from __future__ import annotations

import os

from create_app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("PANEL_HOST", "0.0.0.0")
    port = int(os.environ.get("PANEL_PORT", "8088"))
    app.run(host=host, port=port, debug=False, threaded=True)
