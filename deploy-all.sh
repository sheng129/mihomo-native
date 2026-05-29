#!/usr/bin/env bash
# 部署 mihomo 配置 + TUN 能力 + Web 面板到 N1
set -euo pipefail

N1_IP="${N1_IP:-192.168.5.7}"
N1_USER="${N1_USER:-root}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 部署 mihomo + 面板 -> ${N1_IP} ==="
ping -c 1 -W 2 "$N1_IP" >/dev/null

scp -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  "${DIR}/config.yaml" \
  "${DIR}/mihomo.service" \
  "${N1_USER}@${N1_IP}:/tmp/"

bash "${DIR}/install-panel.sh"

ssh -o BatchMode=yes "${N1_USER}@${N1_IP}" bash -s <<'REMOTE'
set -euo pipefail
cp /tmp/config.yaml /opt/mihomo/config/config.yaml
cp /tmp/mihomo.service /etc/systemd/system/mihomo.service
# geosite 文件名
cd /opt/mihomo/config
[[ -f geosite.dat ]] && [[ ! -f GeoSite.dat ]] && cp -a geosite.dat GeoSite.dat

systemctl daemon-reload
/opt/mihomo/core/mihomo -t -f /opt/mihomo/config/config.yaml
systemctl restart mihomo
sleep 2
systemctl is-active mihomo
systemctl is-active n1-panel
echo "面板: http://$(hostname -I | awk '{print $1}'):8088"
REMOTE

echo "=== 全部完成 ==="
