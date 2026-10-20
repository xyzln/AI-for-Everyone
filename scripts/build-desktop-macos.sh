#!/usr/bin/env bash
# AIE macOS 桌面窗口版构建脚本（在 macOS 上运行）
# 产出：dist/pyinstaller-desktop/AIE.app（原生 .app，WKWebView 渲染，无需浏览器）
# 用法：bash scripts/build-desktop-macos.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> 检查 Python (需要 3.10 - 3.12)..."
PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    ver="$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0.0)"
    maj=${ver%.*}; min=${ver#*.}
    if [ "$maj" = "3" ] && [ "$min" -ge 10 ] && [ "$min" -le 12 ]; then PY="$c"; break; fi
  fi
done
[ -n "$PY" ] || { echo "✘ 未找到 Python 3.10-3.12（brew install python@3.12）" >&2; exit 1; }
echo "    使用 $PY"

VENV="$ROOT/.venv-desktop"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "==> 安装依赖（aife + desktop extra + pyinstaller）..."
pip install -q -e ".[desktop]" "pyinstaller>=6.6"

echo "==> 生成 macOS 图标 icon.icns（从品牌标志渲染 1024 主图）..."
MASTER="$(mktemp -d)/aife-1024.png"
python -c "import sys;sys.path.insert(0,'scripts');from make_icon import make_mark;make_mark(1024).save('$MASTER')"
ICONSET="$(mktemp -d)/AIE.iconset"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$MASTER" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$MASTER" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
sips -z 512 512 "$MASTER" --out "$ICONSET/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$MASTER" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
mkdir -p "$ROOT/aife/assets"
iconutil -c iconset "$ICONSET" -o "$ROOT/aife/assets/icon.icns"
echo "    已生成 aife/assets/icon.icns"

echo "==> PyInstaller 构建窗口版（onedir + .app）..."
pyinstaller packaging/aife_desktop.spec --noconfirm \
  --distpath dist/pyinstaller-desktop --workpath build/pyinstaller-desktop --clean

APP="$ROOT/dist/pyinstaller-desktop/AIE.app"
if [ -d "$APP" ]; then
  echo ""
  echo "✔ 构建完成：$APP"
  echo "   双击 AIE.app 即打开原生桌面窗口（WKWebView，无需浏览器）。"
  echo "   首次运行如被 Gatekeeper 拦截：xattr -dr com.apple.quarantine '$APP'"
else
  echo "✘ 未找到 $APP，请检查上方 PyInstaller 输出。" >&2
  exit 1
fi
