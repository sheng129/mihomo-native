#!/usr/bin/env bash
# N1 旁路由网关模式：WiFi/局域网设备自动经 N1 翻墙
# 在 N1 上以 root 运行: bash setup-gateway.sh
set -euo pipefail

MIHOMO_CFG="/opt/mihomo/config/config.yaml"
LAN_NET="${LAN_NET:-192.168.5.0/24}"
LAN_IF="${LAN_IF:-eth0}"
UPSTREAM_GW="${UPSTREAM_GW:-192.168.5.1}"
N1_IP="${N1_IP:-192.168.5.7}"

[[ "$(id -u)" -eq 0 ]] || { echo "请 root 运行"; exit 1; }

echo "=== N1 旁路由网关配置 ==="
echo "LAN: ${LAN_NET} @ ${LAN_IF}  上游: ${UPSTREAM_GW}  N1: ${N1_IP}"

# 1. 内核转发
sysctl -w net.ipv4.ip_forward=1
mkdir -p /etc/sysctl.d
cat >/etc/sysctl.d/99-n1-gateway.conf <<EOF
net.ipv4.ip_forward=1
net.ipv4.conf.all.rp_filter=0
net.ipv4.conf.${LAN_IF}.rp_filter=0
EOF
sysctl --system >/dev/null 2>&1 || true

# 2. mihomo TUN + auto-redirect（接管经 N1 转发的流量）
python3 <<'PY'
import yaml
from pathlib import Path

p = Path("/opt/mihomo/config/config.yaml")
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
cfg["allow-lan"] = True
cfg["bind-address"] = "0.0.0.0"
cfg["redir-port"] = 7892
dns = cfg.setdefault("dns", {})
dns["enable"] = True
dns["listen"] = "0.0.0.0:53"
dns["enhanced-mode"] = "redir-host"
dns["nameserver"] = ["223.5.5.5", "119.29.29.29"]
dns["fallback"] = ["8.8.8.8"]
dns["nameserver-policy"] = {"geosite:cn,private": ["223.5.5.5", "119.29.29.29"]}
cfg["tun"] = {
    "enable": True,
    "stack": "system",
    "auto-route": True,
    "auto-detect-interface": True,
    "auto-redirect": True,
    "strict-route": False,
    "dns-hijack": ["any:53", "tcp://any:53"],
    "include-interface": ["eth0"],
}
# 旁路由：排除局域网直连，避免回环
cfg["tun"]["inet4-route-exclude-address"] = [
    "192.168.0.0/16",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "127.0.0.0/8",
]
p.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")
print("config.yaml TUN 已更新")
PY

# 3. systemd CAP_NET_ADMIN
SVC="/etc/systemd/system/mihomo.service"
if ! grep -q CAP_NET_ADMIN "$SVC" 2>/dev/null; then
  sed -i '/LimitNOFILE=/a AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE\nCapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE' "$SVC"
fi
systemctl daemon-reload

# 4. iptables NAT（同网段旁路由回程）
IPT_DIR="/etc/n1-gateway"
mkdir -p "$IPT_DIR"
cat >"${IPT_DIR}/iptables.sh" <<SCRIPT
#!/bin/bash
LAN_NET="${LAN_NET}"
LAN_IF="${LAN_IF}"
REDIR_PORT=7892

# 清除旧规则（幂等）
iptables -t nat -D POSTROUTING -s \${LAN_NET} -o \${LAN_IF} -j MASQUERADE 2>/dev/null || true
iptables -t nat -F MIHOMO_LAN 2>/dev/null || true
iptables -t nat -X MIHOMO_LAN 2>/dev/null || true
iptables -t nat -D PREROUTING -j MIHOMO_LAN 2>/dev/null || true
iptables -D FORWARD -i \${LAN_IF} -j ACCEPT 2>/dev/null || true
iptables -D FORWARD -o \${LAN_IF} -j ACCEPT 2>/dev/null || true

# 回程 SNAT
iptables -t nat -A POSTROUTING -s \${LAN_NET} -o \${LAN_IF} -j MASQUERADE
iptables -A FORWARD -i \${LAN_IF} -j ACCEPT
iptables -A FORWARD -o \${LAN_IF} -j ACCEPT

# 局域网 TCP 透明代理 → mihomo redir-port（旁路由核心）
iptables -t nat -N MIHOMO_LAN
iptables -t nat -A MIHOMO_LAN -d 0.0.0.0/8 -j RETURN
iptables -t nat -A MIHOMO_LAN -d 10.0.0.0/8 -j RETURN
iptables -t nat -A MIHOMO_LAN -d 127.0.0.0/8 -j RETURN
iptables -t nat -A MIHOMO_LAN -d 169.254.0.0/16 -j RETURN
iptables -t nat -A MIHOMO_LAN -d 172.16.0.0/12 -j RETURN
iptables -t nat -A MIHOMO_LAN -d 192.168.0.0/16 -j RETURN
iptables -t nat -A MIHOMO_LAN -d 224.0.0.0/4 -j RETURN
iptables -t nat -A MIHOMO_LAN -p tcp -j REDIRECT --to-ports \${REDIR_PORT}
iptables -t nat -A PREROUTING -i \${LAN_IF} -s \${LAN_NET} -p tcp -j MIHOMO_LAN

# 禁用 QUIC(UDP 443)，否则 Chrome/YouTube 不走 TCP 透明代理
iptables -D FORWARD -s \${LAN_NET} -p udp --dport 443 -j DROP 2>/dev/null || true
iptables -I FORWARD 1 -s \${LAN_NET} -p udp --dport 443 -j DROP
SCRIPT
chmod +x "${IPT_DIR}/iptables.sh"
"${IPT_DIR}/iptables.sh"

# 开机恢复 iptables
cat >/etc/systemd/system/n1-gateway-iptables.service <<UNIT
[Unit]
Description=N1 gateway iptables rules
After=network-online.target
Before=mihomo.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=${IPT_DIR}/iptables.sh

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable n1-gateway-iptables.service

# 5. auto-redirect 优先 nftables；无 nft 时用 redir-port + iptables（见下方 MIHOMO_LAN）
if command -v nft >/dev/null 2>&1; then
  echo "nftables 已安装"
else
  echo ">>> 未安装 nftables，使用 redir-port + iptables 透明代理（可稍后 apt install nftables）"
fi
modprobe nf_tables 2>/dev/null || true

# 6. 释放 53 端口给 mihomo
mkdir -p /etc/systemd/resolved.conf.d
cat >/etc/systemd/resolved.conf.d/no-stub.conf <<'RES'
[Resolve]
DNSStubListener=no
RES
systemctl restart systemd-resolved 2>/dev/null || true
# 本机 resolv 指向公共 DNS
printf 'nameserver 223.5.5.5\nnameserver 119.29.29.29\n' >/etc/resolv.conf

# 6. 校验并重启 mihomo
/opt/mihomo/core/mihomo -t -f "$MIHOMO_CFG"
systemctl restart mihomo
sleep 3

echo ""
echo "=== N1 侧配置完成 ==="
systemctl is-active mihomo
ip link show Meta 2>/dev/null | head -1 || echo "WARN: Meta 接口未出现"
ss -lunp | grep ':53' || echo "WARN: 53 端口未监听"
NFT_LINES=$(nft list ruleset 2>/dev/null | wc -l)
echo "nftables 规则行数: ${NFT_LINES}"
if [[ "${NFT_LINES}" -lt 5 ]]; then
  echo "WARN: auto-redirect 可能未生效，请确认已安装 nftables"
fi
dig @127.0.0.1 baidu.com +time=3 +tries=1 +short 2>/dev/null | head -2 || true

cat <<EOF

┌─────────────────────────────────────────────────────────┐
│  还需在主路由 (WiFi) 上改 DHCP（一次即可）              │
├─────────────────────────────────────────────────────────┤
│  默认网关 Gateway  →  ${N1_IP}                          │
│  DNS 服务器        →  ${N1_IP}  （N1 已监听 53）      │
│  备选 DNS          →  223.5.5.5（若 ${N1_IP} 仍异常）  │
└─────────────────────────────────────────────────────────┘

改完后：手机/电脑重连 WiFi，网关应变为 ${N1_IP}
验证：手机浏览器打开 ip.sb 看出口 IP 是否为代理节点

若主路由无法改 DHCP 网关，可在单设备上手动设：
  网关 ${N1_IP}  DNS ${N1_IP}  仍保留 IP 192.168.5.x
EOF
