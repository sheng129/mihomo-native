#!/usr/bin/env bash
# 在本机运行：部署 Web 面板到 N1
set -euo pipefail

N1_IP="${N1_IP:-192.168.5.7}"
N1_USER="${N1_USER:-root}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PANEL_DIR="${DIR}/panel"
REMOTE_DIR="/opt/n1-panel"
PANEL_PASS="${PANEL_PASS:-n1admin}"

ssh_run() {
  ssh -o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new \
    "${N1_USER}@${N1_IP}" "$@"
}
scp_put() {
  scp -o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new -r "$@"
}

echo "=== 部署 N1 Mihomo Web 面板 -> ${N1_IP} ==="
ping -c 1 -W 2 "$N1_IP" >/dev/null

ssh_run "mkdir -p ${REMOTE_DIR} /etc/n1-panel /var/lib/n1-panel"
ssh_run "test -f /etc/n1-panel/settings.json || echo '{\"theme\":\"dark\",\"devices_refresh_sec\":15}' > /etc/n1-panel/settings.json"
scp_put \
  "${PANEL_DIR}/app.py" \
  "${PANEL_DIR}/create_app.py" \
  "${PANEL_DIR}/deps.py" \
  "${PANEL_DIR}/auth.py" \
  "${PANEL_DIR}/autopilot.py" \
  "${PANEL_DIR}/runtime_state.py" \
  "${PANEL_DIR}/panel_helpers.py" \
  "${PANEL_DIR}/config_manager.py" \
  "${PANEL_DIR}/mihomo_api.py" \
  "${PANEL_DIR}/utils.py" \
  "${PANEL_DIR}/traffic_store.py" \
  "${PANEL_DIR}/panel_settings.py" \
  "${PANEL_DIR}/device_manager.py" \
  "${PANEL_DIR}/subscription.py" \
  "${PANEL_DIR}/system_info.py" \
  "${PANEL_DIR}/requirements.txt" \
  "${PANEL_DIR}/routes" \
  "${N1_USER}@${N1_IP}:${REMOTE_DIR}/"
scp_put "${PANEL_DIR}/templates" "${PANEL_DIR}/static" "${N1_USER}@${N1_IP}:${REMOTE_DIR}/"
scp_put "${DIR}/panel.service" "${N1_USER}@${N1_IP}:/etc/systemd/system/n1-panel.service"

ssh_run bash -s <<REMOTE
set -euo pipefail
pip3 install -q -r ${REMOTE_DIR}/requirements.txt 2>/dev/null || pip3 install flask pyyaml segno

if [[ ! -f /etc/n1-panel/env ]]; then
  cat >/etc/n1-panel/env <<EOF
PANEL_PASSWORD=${PANEL_PASS}
PANEL_HOST=0.0.0.0
PANEL_PORT=8088
PANEL_DATA_DIR=/var/lib/n1-panel
PANEL_QUOTA_PATH=/etc/n1-panel/quotas.json
MIHOMO_API=http://127.0.0.1:9090
MIHOMO_CONFIG_DIR=/opt/mihomo/config
MIHOMO_BIN=/opt/mihomo/core/mihomo
EOF
  chmod 600 /etc/n1-panel/env
  echo "已创建 /etc/n1-panel/env（默认密码: ${PANEL_PASS}）"
else
  echo "保留已有 /etc/n1-panel/env"
fi

systemctl daemon-reload
systemctl enable n1-panel
systemctl restart n1-panel
sleep 2
systemctl is-active n1-panel
ss -lntp | grep 8088 || { journalctl -u n1-panel -n 15 --no-pager; exit 1; }
REMOTE

echo ""
echo "=== 部署完成 ==="
echo "访问: http://${N1_IP}:8088"
echo "默认密码: ${PANEL_PASS}（可在 N1 修改 /etc/n1-panel/env 后 systemctl restart n1-panel）"
