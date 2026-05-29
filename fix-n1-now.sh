#!/usr/bin/env bash
set -euo pipefail

N1_IP="${N1_IP:-192.168.5.7}"
N1_USER="${N1_USER:-root}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="/tmp/n1-fix-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

echo "=== N1 修复 v2  日志: $LOG ==="

ping -c 2 -W 2 "$N1_IP"
ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$N1_IP" 2>/dev/null || true

ssh_run() {
  ssh -o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new \
    "${N1_USER}@${N1_IP}" "$@"
}
scp_put() {
  scp -o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new "$@"
}

if ! ssh_run 'echo ok' 2>/dev/null; then
  command -v sshpass >/dev/null || sudo apt-get install -y sshpass
  : "${N1_PASS:?免密失败，请: N1_PASS='密码' bash $0}"
  export SSHPASS="$N1_PASS"
  ssh_run() { sshpass -e ssh -o StrictHostKeyChecking=no "${N1_USER}@${N1_IP}" "$@"; }
  scp_put() { sshpass -e scp -o StrictHostKeyChecking=no "$@"; }
fi

echo ">>> 本机下载 geo 文件（多镜像）"
download_one() {
  local out=$1; shift
  for u in "$@"; do
    echo "try: $u"
    curl -fL --connect-timeout 20 --max-time 300 -o "${DIR}/${out}.tmp" "$u" || continue
    [[ -s "${DIR}/${out}.tmp" ]] || continue
    mv "${DIR}/${out}.tmp" "${DIR}/${out}"
    ls -lh "${DIR}/${out}"
    return 0
  done
  return 1
}

MMDB_URLS=(
  "https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb"
  "https://ghfast.top/https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb"
  "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb"
)
SITE_URLS=(
  "https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geosite.dat"
  "https://ghfast.top/https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat"
)

download_one geoip.metadb "${MMDB_URLS[@]}" || echo "WARN: geoip.metadb 本机下载失败，将依赖 GEOSITE 规则"
download_one geosite.dat "${SITE_URLS[@]}" || echo "WARN: geosite.dat 本机下载失败，用 N1 上已有 GeoSite.dat"

echo ">>> 上传"
ssh_run "mkdir -p /opt/mihomo/config /root/n1-mihomo-native"
scp_put "${DIR}/config.yaml" "${N1_USER}@${N1_IP}:/opt/mihomo/config/"
scp_put "${DIR}/apply-urltest.sh" "${N1_USER}@${N1_IP}:/root/n1-mihomo-native/"
[[ -s "${DIR}/geoip.metadb" ]] && scp_put "${DIR}/geoip.metadb" "${N1_USER}@${N1_IP}:/opt/mihomo/config/" || true
[[ -s "${DIR}/geosite.dat" ]] && scp_put "${DIR}/geosite.dat" "${N1_USER}@${N1_IP}:/opt/mihomo/config/" || true

echo ">>> 远程启动"
ssh_run bash -s <<'REMOTE'
set -euo pipefail
cd /opt/mihomo/config
# mihomo 查找 GeoSite.dat（大小写敏感）
if [[ -f geosite.dat ]] && [[ ! -f GeoSite.dat ]]; then
  cp -a geosite.dat GeoSite.dat
elif [[ -f GeoSite.dat ]] && [[ ! -f geosite.dat ]]; then
  ln -sf GeoSite.dat geosite.dat
fi

systemctl stop mihomo 2>/dev/null || true
pkill -x mihomo 2>/dev/null || true
sleep 1

ls -lh geoip.metadb geosite.dat GeoSite.dat 2>/dev/null || true

# 不要在没有 geosite 时跑会删库的检测；当前规则已去掉 GEOIP
/opt/mihomo/core/mihomo -t -f config.yaml

systemctl enable mihomo
systemctl restart mihomo
sleep 4

echo "--- status ---"
systemctl is-active mihomo
ss -lntp | grep mihomo || { journalctl -u mihomo -n 20 --no-pager; exit 1; }

echo "--- AUTO ---"
curl -s http://127.0.0.1:9090/proxies/AUTO | python3 -c "import sys,json;d=json.load(sys.stdin);print('type:',d.get('type'));print('now:',d.get('now'))"

echo "--- google ---"
curl -x http://127.0.0.1:7890 -I --connect-timeout 20 https://www.google.com | head -5
REMOTE

echo "=== 完成 === $LOG"
