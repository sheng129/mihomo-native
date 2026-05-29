"""概览自动切换与节点筛选。"""
from __future__ import annotations

import time

from deps import DASHBOARD_NODE_LIMIT, mihomo
from panel_helpers import node_to_provider_map
from runtime_state import load_runtime_state, save_runtime_state


def pick_dashboard_nodes(nodes: list[dict], limit: int = DASHBOARD_NODE_LIMIT) -> list[dict]:
    if len(nodes) <= limit:
        return nodes
    selected = next((n for n in nodes if n.get("selected")), None)
    others = [n for n in nodes if not n.get("selected")]
    picked = others[: limit - (1 if selected else 0)]
    out = ([selected] if selected else []) + picked

    def sort_key(n: dict) -> tuple[int, int]:
        d = n.get("delay")
        if d is None or not isinstance(d, (int, float)) or d <= 0:
            return (1, 99999)
        return (0, int(d))

    out.sort(key=sort_key)
    return out[:limit]


def try_autopilot(
    *,
    auto_nodes: dict,
    traffic: dict,
    providers_runtime: dict | None,
    settings: dict,
) -> dict:
    now = time.time()
    state = load_runtime_state()
    interval = int(settings.get("auto_switch_interval_sec", 300))
    if now - float(state.get("auto_last_ts", 0)) < interval:
        return {"ran": False, "reason": "cooldown"}

    nodes = auto_nodes.get("nodes") or []
    current = auto_nodes.get("now") or ""
    if not nodes or not current:
        state["auto_last_ts"] = now
        save_runtime_state(state)
        return {"ran": True, "switched": False, "reason": "no_nodes"}

    node_idx = {n.get("name"): i for i, n in enumerate(nodes)}
    best = nodes[0].get("name")
    action = {"ran": True, "switched": False, "reason": "none"}
    node_provider = node_to_provider_map(providers_runtime)

    if settings.get("traffic_failover_enabled", True):
        threshold = int(settings.get("traffic_failover_threshold", 100))
        by_name = {p.get("name"): p for p in (traffic.get("providers") or [])}
        current_provider = node_provider.get(current, "")
        current_t = by_name.get(current_provider)
        if current_provider and current_t and (current_t.get("usage_percent") or 0) >= threshold:
            exhausted = {
                p.get("name")
                for p in (traffic.get("providers") or [])
                if (p.get("usage_percent") or 0) >= threshold
            }
            candidate = None
            for n in nodes:
                name = n.get("name")
                pvd = node_provider.get(name, "")
                if not pvd or pvd in exhausted:
                    continue
                if name != current:
                    candidate = name
                    break
            if candidate:
                mihomo.select_proxy("AUTO", candidate)
                action = {"ran": True, "switched": True, "reason": "traffic_failover", "to": candidate}

    if not action.get("switched") and settings.get("auto_switch_enabled", True):
        rank = node_idx.get(current, 9999)
        if rank >= DASHBOARD_NODE_LIMIT and best and best != current:
            mihomo.select_proxy("AUTO", best)
            action = {"ran": True, "switched": True, "reason": "not_in_top4", "to": best}

    state["auto_last_ts"] = now
    state["auto_last"] = action
    save_runtime_state(state)
    return action
