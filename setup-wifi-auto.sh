#!/usr/bin/env bash
# WiFi 自动翻墙（旁路由透明代理）— 一键配置 N1
# 路由器设置：网关 192.168.5.7  DNS 192.168.5.7  备用 DNS 留空或 223.5.5.5
# 在 N1 上 root 执行: bash setup-wifi-auto.sh
set -euo pipefail

LAN_NET="${LAN_NET:-192.168.5.0/24}"
LAN_IF="${LAN_IF:-eth0}"
N1_IP="${N1_IP:-192.168.5.7}"
CFG="/opt/mihomo/config/config.yaml"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ "$(id -u)" -eq 0 ]] || { echo "请 root 运行"; exit 1; }

echo "=== WiFi 自动翻墙配置（redir 稳定版）==="

# 1. 内核
sysctl -w net.ipv4.ip_forward=1
mkdir -p /etc/sysctl.d
cat >/etc/sysctl.d/99-n1-gateway.conf <<EOF
net.ipv4.ip_forward=1
net.ipv4.conf.all.rp_filter=0
net.ipv4.conf.${LAN_IF}.rp_filter=0
EOF

# 2. 写入配置（关闭 TUN，用 redir-port + 国内直连规则）
cp "${DIR}/config.yaml" "$CFG" 2>/dev/null || true
python3 <<'PY'
import yaml
from pathlib import Path
p = Path("/opt/mihomo/config/config.yaml")
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
cfg.pop("tproxy-port", None)
cfg["tun"] = {"enable": False}
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
print("config.yaml OK")
PY

# 3. 停 mihomo，清理 TUN/nft
systemctl stop mihomo 2>/dev/null || true
sleep 1
nft flush ruleset 2>/dev/null || true
ip link del Meta 2>/dev/null || true

# 4. iptables：TCP redir + MASQUERADE + 转发
iptables -t mangle -D PREROUTING -i "$LAN_IF" -s "$LAN_NET" -j MIHOMO_TPROXY 2>/dev/null || true
iptables -t mangle -F MIHOMO_TPROXY 2>/dev/null || true
iptables -t mangle -X MIHOMO_TPROXY 2>/dev/null || true

iptables -t nat -D PREROUTING -i "$LAN_IF" -s "$LAN_NET" -p tcp -j MIHOMO_LAN 2>/dev/null || true
iptables -t nat -F MIHOMO_LAN 2>/dev/null || true
iptables -t nat -X MIHOMO_LAN 2>/dev/null || true
iptables -t nat -N MIHOMO_LAN
for c in 0.0.0.0/8 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4; do
  iptables -t nat -A MIHOMO_LAN -d "$c" -j RETURN
done
iptables -t nat -A MIHOMO_LAN -p tcp -j REDIRECT --to-ports 7892
iptables -t nat -A PREROUTING -i "$LAN_IF" -s "$LAN_NET" -p tcp -j MIHOMO_LAN

IPT_DIR="/etc/n1-gateway"
mkdir -p "$IPT_DIR"
cat >"${IPT_DIR}/iptables.sh" <<SCRIPT
#!/bin/bash
LAN_NET="${LAN_NET}"
LAN_IF="${LAN_IF}"
iptables -t nat -D POSTROUTING -s \${LAN_NET} -o \${LAN_IF} -j MASQUERADE 2>/dev/null || true
iptables -D FORWARD -i \${LAN_IF} -j ACCEPT 2>/dev/null || true
iptables -D FORWARD -o \${LAN_IF} -j ACCEPT 2>/dev/null || true
iptables -t nat -A POSTROUTING -s \${LAN_NET} -o \${LAN_IF} -j MASQUERADE
iptables -I FORWARD 1 -i \${LAN_IF} -j ACCEPT
iptables -I FORWARD 1 -o \${LAN_IF} -j ACCEPT
SCRIPT
chmod +x "${IPT_DIR}/iptables.sh"
"${IPT_DIR}/iptables.sh"

ufw allow in on "$LAN_IF" from "$LAN_NET" 2>/dev/null || true
ufw route allow in on "$LAN_IF" from "$LAN_NET" 2>/dev/null || true

# 5. DNS 53
mkdir -p /etc/systemd/resolved.conf.d
cat >/etc/systemd/resolved.conf.d/no-stub.conf <<'RES'
[Resolve]
DNSStubListener=no
RES
systemctl restart systemd-resolved 2>/dev/null || true
printf 'nameserver 223.5.5.5\n' >/etc/resolv.conf

# 6. systemd 权限
SVC="/etc/systemd/system/mihomo.service"
grep -q CAP_NET_ADMIN "$SVC" 2>/dev/null || sed -i '/LimitNOFILE=/a AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE\nCapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE' "$SVC"
systemctl daemon-reload

# 7. 启动
/opt/mihomo/core/mihomo -t -f "$CFG"
systemctl start mihomo
sleep 4

echo ""
echo "=== 完成 ==="
systemctl is-active mihomo
ss -lntp | grep -E ':7892|:53' | head -3
iptables -t nat -L MIHOMO_LAN -n -v | tail -2
dig @127.0.0.1 baidu.com +short +time=2 | head -1
dig @127.0.0.1 google.com +short +time=2 | head -1

cat <<EOF

┌─ 中兴路由器 BE5100 ─────────────────────────┐
│  自定义网关:  ${N1_IP}                       │
│  DNS:         ${N1_IP}                       │
│  备用 DNS:    留空 或 223.5.5.5              │
└────────────────────────────────────────────┘

连接 WiFi 即自动翻墙，无需在手机设代理。
国内走直连，国外走 AUTO。

EOF
