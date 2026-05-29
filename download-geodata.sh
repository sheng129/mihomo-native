#!/usr/bin/env bash
# 在你这台 Linux 电脑（能访问外网）上运行，再 scp 到 N1
set -euo pipefail

N1_IP="${N1_IP:-192.168.5.7}"
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$OUT_DIR"

GEOIP_URLS=(
  "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb"
  "https://ghfast.top/https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb"
  "https://mirror.ghproxy.com/https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb"
)

download() {
  local name=$1
  shift
  local urls=("$@")
  for u in "${urls[@]}"; do
    echo ">>> 尝试下载 ${name}: $u"
    if curl -fL --connect-timeout 20 --max-time 300 -o "${name}.tmp" "$u" && [[ -s "${name}.tmp" ]]; then
      mv "${name}.tmp" "$name"
      ls -lh "$name"
      return 0
    fi
    rm -f "${name}.tmp"
  done
  return 1
}

download geoip.metadb "${GEOIP_URLS[@]}" || { echo "geoip.metadb 下载失败"; exit 1; }

echo ""
echo ">>> 上传到 N1 (${N1_IP})..."
scp geoip.metadb "root@${N1_IP}:/opt/mihomo/config/"

echo ""
echo ">>> 在 N1 上校验并重启（需已 SSH 可达）"
ssh "root@${N1_IP}" 'cd /opt/mihomo/config && /opt/mihomo/core/mihomo -t -f config.yaml && systemctl restart mihomo && systemctl is-active mihomo'

echo "完成。可在 N1 执行: bash /root/n1-mihomo-native/apply-urltest.sh 做完整验证"
