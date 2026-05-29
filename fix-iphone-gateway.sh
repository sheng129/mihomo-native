#!/usr/bin/env bash
# iPhone/旁路由：TPROXY 接管 TCP+UDP，修复 YouTube/Google
set -euo pipefail

LAN_NET="${LAN_NET:-192.168.5.0/24}"
LAN_IF="${LAN_IF:-eth0}"
TPROXY_PORT=7893
MARK=0x1
TABLE=100

[[ "$(id -u)" -eq 0 ]] || { echo "请 root 运行"; exit 1; }

python3 <<'PY'
import yaml
from pathlib import Path
p = Path("/opt/mihomo/config/config.yaml")
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
cfg["tproxy-port"] = 7893
cfg["redir-port"] = 7892
dns = cfg.setdefault("dns", {})
dns["enable"] = True
dns["listen"] = "0.0.0.0:53"
dns["enhanced-mode"] = "fake-ip"
dns["fake-ip-range"] = "198.18.0.1/16"
dns["nameserver"] = ["223.5.5.5", "119.29.29.29"]
dns["fallback"] = ["8.8.8.8"]
dns["nameserver-policy"] = {"geosite:cn,private": ["223.5.5.5", "119.29.29.29"]}
p.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
print("config: tproxy-port + fake-ip dns")
PY

# TPROXY 路由
ip rule del fwmark $MARK table $TABLE 2>/dev/null || true
ip route flush table $TABLE 2>/dev/null || true
ip rule add fwmark $MARK table $TABLE
ip route add local default dev lo table $TABLE

# 清除旧规则
iptables -t mangle -D PREROUTING -i "$LAN_IF" -s "$LAN_NET" -j MIHOMO_TPROXY 2>/dev/null || true
iptables -t mangle -F MIHOMO_TPROXY 2>/dev/null || true
iptables -t mangle -X MIHOMO_TPROXY 2>/dev/null || true
iptables -D FORWARD -s "$LAN_NET" -p udp --dport 443 -j DROP 2>/dev/null || true
iptables -D FORWARD -s "$LAN_NET" -p udp --dport 853 -j DROP 2>/dev/null || true
iptables -D FORWARD -s "$LAN_NET" -p tcp --dport 853 -j DROP 2>/dev/null || true

iptables -t mangle -N MIHOMO_TPROXY
for cidr in 0.0.0.0/8 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4; do
  iptables -t mangle -A MIHOMO_TPROXY -d "$cidr" -j RETURN
done
iptables -t mangle -A MIHOMO_TPROXY -p tcp -j TPROXY --on-port "$TPROXY_PORT" --tproxy-mark "$MARK/$MARK"
iptables -t mangle -A MIHOMO_TPROXY -p udp -j TPROXY --on-port "$TPROXY_PORT" --tproxy-mark "$MARK/$MARK"
iptables -t mangle -A PREROUTING -i "$LAN_IF" -s "$LAN_NET" -j MIHOMO_TPROXY

# 禁止 DoT，迫使走 N1:53（iPhone 常偷偷用 853）
iptables -I FORWARD 1 -s "$LAN_NET" -p udp --dport 853 -j DROP
iptables -I FORWARD 1 -s "$LAN_NET" -p tcp --dport 853 -j DROP

# 保留 TCP redir 作备用（部分内核 TPROXY 对 tcp 不稳时）
iptables -t nat -C PREROUTING -i "$LAN_IF" -s "$LAN_NET" -p tcp -j MIHOMO_LAN 2>/dev/null || \
  iptables -t nat -A PREROUTING -i "$LAN_IF" -s "$LAN_NET" -p tcp -j MIHOMO_LAN 2>/dev/null || true

/opt/mihomo/core/mihomo -t -f /opt/mihomo/config/config.yaml
systemctl restart mihomo
sleep 4

echo "=== 完成 ==="
systemctl is-active mihomo
ss -lntp | grep -E "7892|7893|53"
iptables -t mangle -L MIHOMO_TPROXY -n -v | tail -4
echo ""
echo "iPhone 请检查："
echo "  1. 设置-WiFi-此网络-DNS 手动仅 192.168.5.7"
echo "  2. 关闭 iCloud 专用代理 (Private Relay)"
echo "  3. 关闭 限制 IP 地址跟踪"
echo "  4. 忽略此 WiFi 后重新连接"
