#!/usr/bin/env bash
# 在你这台 HP 上运行一次：配置免密 SSH 并自动修复 N1 mihomo
set -euo pipefail

N1_IP="${N1_IP:-192.168.5.7}"
N1_USER="${N1_USER:-root}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="/tmp/n1-fix.log"

exec > >(tee -a "$LOG") 2>&1
echo "=== N1 修复 $(date -Iseconds) === IP=${N1_IP}"

ping -c 2 -W 2 "$N1_IP" || { echo "ping 失败，检查是否同一局域网"; exit 1; }
nc -zv -w 3 "$N1_IP" 22 || { echo "SSH 22 端口不通"; exit 1; }

ssh_cmd() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
    "${N1_USER}@${N1_IP}" "$@"
}

if ! ssh_cmd 'echo ok' 2>/dev/null; then
  echo ">>> 免密失败，尝试 sshpass（请勿在脚本里写密码，用环境变量）"
  command -v sshpass >/dev/null || sudo apt-get install -y sshpass
  export SSHPASS="${N1_PASS:-}"
  [[ -n "$SSHPASS" ]] || { echo "请: N1_PASS='你的密码' bash $0"; exit 1; }
  ssh_cmd() {
    sshpass -e ssh -o StrictHostKeyChecking=no "${N1_USER}@${N1_IP}" "$@"
  }
  scp_cmd() {
    sshpass -e scp -o StrictHostKeyChecking=no "$@"
  }
else
  scp_cmd() { scp -o StrictHostKeyChecking=accept-new "$@"; }
fi

echo ">>> 下载 geoip.metadb（本机）"
if [[ ! -s "${DIR}/geoip.metadb" ]]; then
  for u in \
    "https://ghfast.top/https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb" \
    "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb"
  do
    curl -fL --connect-timeout 20 --max-time 300 -o "${DIR}/geoip.metadb" "$u" && break
  done
fi
[[ -s "${DIR}/geoip.metadb" ]] || { echo "请手动下载 geoip.metadb 到 ${DIR}/"; exit 1; }
ls -lh "${DIR}/geoip.metadb"

echo ">>> 上传配置与 Geo 库"
ssh_cmd "mkdir -p /root/n1-mihomo-native"
scp_cmd "${DIR}/geoip.metadb" "${DIR}/config.yaml" \
  "${N1_USER}@${N1_IP}:/opt/mihomo/config/"
scp_cmd "${DIR}/apply-urltest.sh" "${DIR}/config.yaml" \
  "${N1_USER}@${N1_IP}:/root/n1-mihomo-native/"

echo ">>> 远程校验并重启"
ssh_cmd bash -s <<'REMOTE'
set -euo pipefail
cp /root/n1-mihomo-native/config.yaml /opt/mihomo/config/config.yaml
cd /opt/mihomo/config
ls -lh geoip.metadb
/opt/mihomo/core/mihomo -t -f config.yaml
systemctl restart mihomo
sleep 2
systemctl is-active mihomo
curl -s http://127.0.0.1:9090/proxies/AUTO | python3 -c "import sys,json; d=json.load(sys.stdin); print('AUTO type:', d.get('type')); print('now:', d.get('now'))" 2>/dev/null || true
curl -x http://127.0.0.1:7890 -I --connect-timeout 15 https://www.google.com | head -3
REMOTE

echo "=== 完成，日志: $LOG ==="
