"""通用工具"""
from __future__ import annotations

import re
from urllib.parse import urlparse


def mask_url(url: str) -> str:
    """订阅链接半隐藏：保留协议+域名，路径/token 打码"""
    if not url:
        return ""
    try:
        p = urlparse(url)
        host = p.netloc or "?"
        scheme = p.scheme or "https"
        path = p.path or ""
        if len(path) > 12:
            path = path[:6] + "****" + path[-4:]
        elif path:
            path = "****"
        query = ""
        if p.query:
            query = "?****"
        return f"{scheme}://{host}{path}{query}"
    except Exception:
        if len(url) <= 16:
            return "****"
        return url[:8] + "****" + url[-4:]


def bytes_to_gb(n: int | float) -> float:
    return float(n or 0) / 1024 / 1024 / 1024
