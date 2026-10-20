#!/usr/bin/env bash
# AIE Linux 安装脚本
# 用法 (项目根目录): bash scripts/install-linux.sh
# 幂等: 已存在 .venv 且 aife 可用则跳过；失败给出可复制修复命令。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"

echo "==> 检查 Python (需要 3.10 - 3.12)..."
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "✘ 未找到 Python 3.10-3.12。请先安装: sudo apt install python3.10 python3.10-venv" >&2
  exit 1
fi
ver=$("$PY" -c "import sys; print('%d.%d' % sys.version_info[:2])")
maj=${ver%.*}; min=${ver#*.}
if [ "$maj" -ne 3 ] || [ "$min" -lt 10 ] || [ "$min" -gt 12 ]; then
  echo "✘ Python 版本 $ver 不在 3.10-3.12 范围。" >&2; exit 1
fi
echo "    使用 $PY ($ver)"

if [ -x "$VENV/bin/aife" ]; then
  echo "==> 检测到已安装，跳过创建 venv。"
else
  echo "==> 创建虚拟环境 $VENV ..."
  "$PY" -m venv "$VENV"
fi

echo "==> 安装 aife ..."
"$VENV/bin/pip" install -e "$ROOT"
"$VENV/bin/python" -c "import aife; print('aife', aife.__version__)" >/dev/null

echo ""
echo "✔ 安装完成！"
echo "   下一步:"
echo "     source $VENV/bin/activate"
echo "     aife setup      # 一键部署"
