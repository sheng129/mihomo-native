#!/usr/bin/env bash
# 在 N1 上以 root 执行；或从本机: scp 后 ssh 运行
set -euo pipefail

CFG_DIR="/opt/mihomo/config"
CFG="${CFG_DIR}/config.yaml"
BIN="/opt/mihomo/core/mihomo"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ "$(id -u)" -eq 0 ]] || { echo "请 root 运行"; exit 1; }

if [[ -f "${SCRIPT_DIR}/config.yaml" ]]; then
  cp -a "$CFG" "${CFG}.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
  cp "${SCRIPT_DIR}/config.yaml" "$CFG"
  echo "已安装 ${SCRIPT_DIR}/config.yaml -> $CFG"
else
  echo "未找到 ${SCRIPT_DIR}/config.yaml，请手动编辑 $CFG"
  exit 1
fi

cd "$CFG_DIR"

# 统一 geosite 文件名（mihomo 读取 GeoSite.dat，大小写敏感）
if [[ -f geosite.dat ]] && [[ ! -f GeoSite.dat ]]; then
  cp -a geosite.dat GeoSite.dat
elif [[ -f GeoSite.dat ]] && [[ ! -f geosite.dat ]]; then
  ln -sf GeoSite.dat geosite.dat
fi

if grep -qE '^\s*-\s*GEOIP,' "$CFG" 2>/dev/null; then
  if [[ ! -s geoip.metadb ]] || [[ "$(stat -c%s geoip.metadb)" -lt 1000000 ]]; then
    echo ""
    echo "ERROR: 配置含 GEOIP 规则但缺少有效 geoip.metadb"
    echo "请在你电脑上执行: N1_IP=192.168.5.7 bash ~/n1-mihomo-native/download-geodata.sh"
    exit 1
  fi
elif [[ ! -s geosite.dat ]] && [[ ! -s GeoSite.dat ]]; then
  echo ""
  echo "ERROR: 配置使用 GEOSITE 规则但缺少 geosite.dat / GeoSite.dat"
  echo "请在你电脑上执行: N1_IP=192.168.5.7 bash ~/n1-mihomo-native/download-geodata.sh"
  exit 1
fi

# 无效 MMDB 会触发联网下载并超时；GEOSITE 规则下不需要
if ! grep -qE '^\s*-\s*GEOIP,' "$CFG" 2>/dev/null && [[ -f geoip.metadb ]]; then
  rm -f geoip.metadb
fi

"$BIN" -t -f "$CFG"
systemctl restart mihomo
sleep 3

echo "=== 触发 AUTO 组测速 ==="
curl -sG "http://127.0.0.1:9090/group/AUTO/delay" \
  --data-urlencode "url=http://www.gstatic.com/generate_204" \
  --data-urlencode "timeout=8000" | python3 -m json.tool 2>/dev/null | head -30 || true

echo ""
echo "=== 当前 AUTO 选中节点 ==="
curl -s "http://127.0.0.1:9090/proxies/AUTO" | python3 -c "import sys,json; d=json.load(sys.stdin); print('now:', d.get('now')); print('alive:', d.get('alive'))"

echo ""
echo "=== 测试 Google ==="
curl -x http://127.0.0.1:7890 -I --connect-timeout 20 https://www.google.com | head -5
