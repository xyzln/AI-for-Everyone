#!/usr/bin/env bash
# AIE Linux 桌面窗口版构建脚本（在 Linux 上运行）
# 产出：dist/pyinstaller-desktop/aife/（onedir，含 aife 可执行；GTK WebKit 渲染）
# 用法：bash scripts/build-desktop-linux.sh
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
[ -n "$PY" ] || { echo "✘ 未找到 Python 3.10-3.12" >&2; exit 1; }
echo "    使用 $PY"

# pywebview 的 GTK 后端依赖系统 WebKit2 运行时（缺失时窗口创建会失败并回退浏览器）
if ! pkg-config --exists webkit2gtk-4.1 2>/dev/null && ! pkg-config --exists webkit2gtk-4.0 2>/dev/null; then
  echo "⚠ 未检测到 WebKit2GTK。请先安装（Debian/Ubuntu）：" >&2
  echo "    sudo apt install python3-gi gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0" >&2
  echo "  （Fedora）sudo dnf install webkit2gtk4.1 python3-gobject" >&2
  echo "  继续构建，但运行时若缺运行时会自动回退浏览器。" >&2
fi

VENV="$ROOT/.venv-desktop"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "==> 安装依赖（aife + desktop extra + pyinstaller）..."
pip install -q -e ".[desktop]" "pyinstaller>=6.6"

echo "==> 准备 Linux 窗口图标（icon.png）..."
mkdir -p "$ROOT/aife/assets"
cp -f "$ROOT/web/assets/logo.png" "$ROOT/aife/assets/icon.png"

echo "==> PyInstaller 构建窗口版（onedir）..."
pyinstaller packaging/aife_desktop.spec --noconfirm \
  --distpath dist/pyinstaller-desktop --workpath build/pyinstaller-desktop --clean

EXE="$ROOT/dist/pyinstaller-desktop/aife/aife"
if [ -x "$EXE" ]; then
  echo ""
  echo "✔ 构建完成：$ROOT/dist/pyinstaller-desktop/aife/"
  echo "   运行：$EXE            （无参=打开原生桌面窗口）"
  echo "   或：  $EXE serve       （仅起服务，走浏览器）"
else
  echo "✘ 未找到可执行 $EXE，请检查上方 PyInstaller 输出。" >&2
  exit 1
fi
