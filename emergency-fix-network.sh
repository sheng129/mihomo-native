#!/usr/bin/env bash
# 紧急修复：关闭 TUN，用 redir + 国内直连，恢复内外网
set -euo pipefail
LAN_NET="192.168.5.0/24"
LAN_IF="eth0"
CFG="/opt/mihomo/config/config.yaml"

[[ "$(id -u)" -eq 0 ]] || exit 1

echo "=== 紧急修复网络 ==="

python3 <<'PY'
import yaml
from pathlib import Path
p = Path("/opt/mihomo/config/config.yaml")
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
cfg["tun"] = {"enable": False}
cfg.pop("tproxy-port", None)
cfg["redir-port"] = 7892
cfg["allow-lan"] = True
cfg["mode"] = "rule"
cfg["dns"] = {
    "enable": True,
    "listen": "0.0.0.0:53",
    "ipv6": False,
    "enhanced-mode": "redir-host",
    "nameserver": ["223.5.5.5", "119.29.29.29"],
    "fallback": ["8.8.8.8"],
    "nameserver-policy": {"geosite:cn,private": ["223.5.5.5", "119.29.29.29"]},
}
cfg["rules"] = [
    "GEOSITE,cn,DIRECT",
    "GEOSITE,private,DIRECT",
    "GEOIP,CN,DIRECT",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "GEOSITE,google,AUTO",
    "GEOSITE,youtube,AUTO",
    "MATCH,AUTO",
]
p.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
print("config OK")
PY

# 停 mihomo 清 nft
systemctl stop mihomo
sleep 1
nft flush ruleset 2>/dev/null || true
ip link del Meta 2>/dev/null || true

# 清理 mangle
iptables -t mangle -D PREROUTING -i "$LAN_IF" -s "$LAN_NET" -j MIHOMO_TPROXY 2>/dev/null || true
iptables -t mangle -F MIHOMO_TPROXY 2>/dev/null || true
iptables -t mangle -X MIHOMO_TPROXY 2>/dev/null || true

# TCP 透明代理
iptables -t nat -D PREROUTING -i "$LAN_IF" -s "$LAN_NET" -p tcp -j MIHOMO_LAN 2>/dev/null || true
iptables -t nat -F MIHOMO_LAN 2>/dev/null || true
iptables -t nat -X MIHOMO_LAN 2>/dev/null || true
iptables -t nat -N MIHOMO_LAN
for c in 0.0.0.0/8 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4; do
  iptables -t nat -A MIHOMO_LAN -d "$c" -j RETURN
done
iptables -t nat -A MIHOMO_LAN -p tcp -j REDIRECT --to-ports 7892
iptables -t nat -A PREROUTING -i "$LAN_IF" -s "$LAN_NET" -p tcp -j MIHOMO_LAN

# 回程 + 转发
iptables -t nat -D POSTROUTING -s "$LAN_NET" -o "$LAN_IF" -j MASQUERADE 2>/dev/null || true
iptables -D FORWARD -i "$LAN_IF" -j ACCEPT 2>/dev/null || true
iptables -D FORWARD -o "$LAN_IF" -j ACCEPT 2>/dev/null || true
iptables -t nat -A POSTROUTING -s "$LAN_NET" -o "$LAN_IF" -j MASQUERADE
iptables -I FORWARD 1 -i "$LAN_IF" -j ACCEPT
iptables -I FORWARD 1 -o "$LAN_IF" -j ACCEPT

# 去掉 DoT 封锁（避免 DNS 异常）
while iptables -D FORWARD -s "$LAN_NET" -p udp --dport 853 -j DROP 2>/dev/null; do :; done
while iptables -D FORWARD -s "$LAN_NET" -p tcp --dport 853 -j DROP 2>/dev/null; do :; done

# UFW 放行转发
ufw allow in on eth0 from "$LAN_NET" 2>/dev/null || true
ufw route allow in on eth0 from "$LAN_NET" 2>/dev/null || true

/opt/mihomo/core/mihomo -t -f "$CFG"
systemctl start mihomo
sleep 4

echo "active: $(systemctl is-active mihomo)"
ss -lntp | grep -E '7892|53' | head -3
iptables -t nat -L MIHOMO_LAN -n -v | tail -2
curl -s --max-time 8 -o /dev/null -w "baidu:%{http_code} google:%{http_code}\n" http://www.baidu.com -x http://127.0.0.1:7890 https://www.google.com
