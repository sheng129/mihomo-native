#!/usr/bin/env bash
# 在 N1 Armbian 上以 root 执行：bash install-on-n1.sh
set -euo pipefail

MIHOMO_BIN="/opt/mihomo/core/mihomo"
MIHOMO_DIR="/opt/mihomo/config"
SERVICE_NAME="mihomo"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 运行"
  exit 1
fi

if [[ ! -x "$MIHOMO_BIN" ]]; then
  echo "找不到可执行文件: $MIHOMO_BIN"
  exit 1
fi

CONF=""
if [[ -f "${MIHOMO_DIR}/config.yaml" ]]; then
  CONF="${MIHOMO_DIR}/config.yaml"
else
  CONF="$(find "${MIHOMO_DIR}" -maxdepth 2 -name 'config.yaml' -type f 2>/dev/null | head -1)"
fi
if [[ -z "$CONF" ]]; then
  echo "未在 ${MIHOMO_DIR} 找到 config.yaml，请确认配置目录"
  exit 1
fi
echo "使用配置: $CONF"

echo "=== 配置语法检查 ==="
"$MIHOMO_BIN" -t -f "$CONF"

echo "=== 安装 systemd 单元 ==="
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/mihomo.service" ]]; then
  cp "${SCRIPT_DIR}/mihomo.service" "/etc/systemd/system/${SERVICE_NAME}.service"
else
  cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<'UNIT'
[Unit]
Description=Mihomo proxy (native, no Docker)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mihomo/config
ExecStart=/opt/mihomo/core/mihomo -d /opt/mihomo/config
Restart=on-failure
RestartSec=5
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
UNIT
fi

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "=== 服务状态 ==="
systemctl status "${SERVICE_NAME}" --no-pager -l || true

echo ""
echo "若配置里启用了 TUN，需在 service 中加上 CAP_NET_ADMIN，然后:"
echo "  systemctl daemon-reload && systemctl restart ${SERVICE_NAME}"
echo ""
echo "查看日志: journalctl -u ${SERVICE_NAME} -f"
