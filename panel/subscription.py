"""机场订阅类型：Mihomo proxy-providers (http / file / inline) 与常用参数"""
from __future__ import annotations

import re
from typing import Any

import yaml

VALID_PROVIDER_TYPES = ("http", "file", "inline")

PROVIDER_TYPE_META: dict[str, dict[str, Any]] = {
    "http": {
        "label": "远程订阅 (HTTP)",
        "short": "HTTP",
        "description": "Clash / Clash Meta / Mihomo 订阅链接，定时自动更新",
        "needs_url": True,
        "needs_path": False,
        "needs_payload": False,
        "supports_headers": True,
        "supports_qr": True,
    },
    "file": {
        "label": "本地文件",
        "short": "FILE",
        "description": "读取 N1 上 Mihomo 目录内的节点 YAML（path 相对配置目录）",
        "needs_url": False,
        "needs_path": True,
        "needs_payload": False,
        "supports_headers": False,
        "supports_qr": False,
    },
    "inline": {
        "label": "内联节点",
        "short": "INLINE",
        "description": "直接写入节点列表（YAML 数组），适合手动维护或粘贴转换结果",
        "needs_url": False,
        "needs_path": False,
        "needs_payload": True,
        "supports_headers": False,
        "supports_qr": False,
    },
}

# 面板展示用：机场常见订阅形态说明（实际均映射到 http/file/inline）
SUBSCRIPTION_PRESETS: list[dict[str, Any]] = [
    {
        "id": "clash",
        "label": "Clash 订阅",
        "provider_type": "http",
        "hint": "机场后台复制的 HTTPS 订阅链接",
        "url_placeholder": "https://example.com/sub?token=xxx",
    },
    {
        "id": "clashmeta",
        "label": "Clash Meta / Mihomo",
        "provider_type": "http",
        "hint": "同上；若节点异常可在链接后加 ?flag=meta 或按机场文档转换",
        "url_placeholder": "https://example.com/sub?target=clashmeta",
    },
    {
        "id": "token_header",
        "label": "Token / 鉴权订阅",
        "provider_type": "http",
        "hint": "需在下方填写 Authorization 或自定义请求头",
        "url_placeholder": "https://example.com/api/v1/client/subscribe?token=...",
        "default_headers": {"Authorization": "Bearer "},
    },
    {
        "id": "local_file",
        "label": "本地 YAML",
        "provider_type": "file",
        "hint": "如 ./providers/myairport.yaml（需已上传到 N1 配置目录）",
        "path_placeholder": "./providers/myairport.yaml",
    },
    {
        "id": "inline",
        "label": "手动节点",
        "provider_type": "inline",
        "hint": "粘贴 proxies 列表 YAML，格式同 Clash 节点段",
    },
]


def list_provider_types() -> list[dict[str, Any]]:
    return [
        {"id": k, **v}
        for k, v in PROVIDER_TYPE_META.items()
    ]


def type_label(provider_type: str) -> str:
    meta = PROVIDER_TYPE_META.get(provider_type) or {}
    return meta.get("label") or provider_type


def normalize_provider_type(value: str | None) -> str:
    t = (value or "http").strip().lower()
    if t in VALID_PROVIDER_TYPES:
        return t
    raise ValueError(f"订阅类型必须是: {', '.join(VALID_PROVIDER_TYPES)}")


def _parse_headers(raw: Any) -> dict[str, list[str]] | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        out: dict[str, list[str]] = {}
        for k, v in raw.items():
            if not k:
                continue
            if isinstance(v, list):
                out[str(k)] = [str(x) for x in v]
            else:
                out[str(k)] = [str(v)]
        return out or None
    if isinstance(raw, str) and raw.strip():
        try:
            data = yaml.safe_load(raw)
            if isinstance(data, dict):
                return _parse_headers(data)
        except yaml.YAMLError:
            pass
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        out = {}
        for ln in lines:
            if ":" not in ln:
                continue
            k, v = ln.split(":", 1)
            out[k.strip()] = [v.strip()]
        return out or None
    return None


def _parse_payload(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        raise ValueError("内联节点内容不能为空")
    if isinstance(raw, list):
        if not all(isinstance(x, dict) for x in raw):
            raise ValueError("内联节点必须是对象数组")
        return raw
    text = str(raw).strip()
    if not text:
        raise ValueError("内联节点内容不能为空")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"内联 YAML 解析失败: {e}") from e
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("proxies"), list):
        return data["proxies"]
    raise ValueError("内联内容需为节点列表 YAML，或包含 proxies: 字段")


def detect_provider_type_from_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return "http"
    if u.startswith(("http://", "https://")):
        return "http"
    if u.endswith((".yaml", ".yml")) or u.startswith(("./", "/")):
        return "file"
    return "http"


def build_provider_spec(
    provider_type: str,
    *,
    name_key: str,
    url: str = "",
    path: str | None = None,
    payload: Any = None,
    interval: int = 3600,
    headers: Any = None,
    user_agent: str | None = None,
    filter_regex: str | None = None,
    exclude_filter: str | None = None,
) -> dict[str, Any]:
    """生成写入 config.yaml 的 proxy-provider 条目。"""
    ptype = normalize_provider_type(provider_type)
    spec: dict[str, Any] = {
        "type": ptype,
        "health-check": {
            "enable": True,
            "interval": 600,
            "url": "http://www.gstatic.com/generate_204",
        },
    }

    hdr = _parse_headers(headers) or {}
    if user_agent and user_agent.strip():
        hdr["User-Agent"] = [user_agent.strip()]
    if hdr:
        spec["header"] = hdr

    if ptype == "http":
        if not url.strip():
            raise ValueError("远程订阅必须填写订阅 URL")
        spec["url"] = url.strip()
        spec["interval"] = max(300, int(interval))
        spec["path"] = path or f"./providers/{name_key}.yaml"
    elif ptype == "file":
        p = (path or url or "").strip()
        if not p:
            raise ValueError("本地文件必须填写 path（如 ./providers/xxx.yaml）")
        spec["path"] = p
    elif ptype == "inline":
        spec["payload"] = _parse_payload(payload)
        spec["path"] = path or f"./providers/{name_key}.yaml"

    if filter_regex:
        spec["filter"] = filter_regex
    if exclude_filter:
        spec["exclude-filter"] = exclude_filter
    return spec


def provider_public_meta(spec: dict[str, Any]) -> dict[str, Any]:
    ptype = spec.get("type", "http")
    return {
        "type": ptype,
        "type_label": type_label(ptype),
        "has_url": bool(spec.get("url")),
        "path": spec.get("path", ""),
        "interval": spec.get("interval"),
        "supports_qr": PROVIDER_TYPE_META.get(ptype, {}).get("supports_qr", False),
    }
