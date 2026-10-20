#!/usr/bin/env bash
# AIE build-release.sh — 打包分平台 zip + GitHub 上传包 + SHA256SUMS
# 用法: bash scripts/build-release.sh            # 用当前版本号
#       VERSION=0.1.0 bash scripts/build-release.sh
# 依赖: git, zip, sha256sum (Git Bash / Linux / macOS 自带；缺失时给 Python fallback)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ---- 版本号提取 ----
if [ -z "${VERSION:-}" ]; then
  VERSION="$(grep -m1 '__version__' aife/__init__.py | sed -E "s/.*__version__\s*=\s*['\"]([^'\"]+)['\"].*/\1/")"
fi
[ -n "$VERSION" ] || { echo "ERROR: 无法提取版本号" >&2; exit 1; }
echo "==> AIE 版本: $VERSION"

DIST="$ROOT/dist"
STAGE="$DIST/stage"
rm -rf "$DIST" "$STAGE"
mkdir -p "$DIST" "$STAGE"

# ---- 大小预算 (字节) ----
GITHUB_MAX=$((100 * 1024 * 1024))   # 100MB 硬约束
PLATFORM_MAX=$((30 * 1024 * 1024))  # 30MB 目标

# ---- 排除规则 ----
EXCLUDES=(
  --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc'
  --exclude='runs' --exclude='web/mock' --exclude='.pytest_cache'
  --exclude='.git' --exclude='dist' --exclude='*.egg-info'
  --exclude='.idea' --exclude='.vscode'
)

# ---- 收集源树到 staging ----
echo "==> 组装源码树到 $STAGE"
# 优先用 git，能干净排除忽略项；否则用 cp + 排除
if git -C "$ROOT" rev-parse >/dev/null 2>&1; then
  git archive --format=tar HEAD | tar -x -C "$STAGE"
else
  cp -R aife web config scripts tests docs pyproject.toml README.md LICENSE .gitignore "$STAGE"/ 2>/dev/null || true
fi
# 无论如何强制删除不该入包的内容
rm -rf "$STAGE/.venv" "$STAGE/web/mock" "$STAGE/runs" "$STAGE/dist" 2>/dev/null || true
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true

# 没有 LICENSE/README 时给最小占位，保证 GitHub 包合规
[ -f "$STAGE/LICENSE" ] || cp LICENSE "$STAGE/LICENSE" 2>/dev/null || printf 'MIT License\n' > "$STAGE/LICENSE"
[ -f "$STAGE/README.md" ] || cp README.md "$STAGE/README.md" 2>/dev/null || printf '# AIE\n' > "$STAGE/README.md"

# ---- 打包函数 ----
zip_available() { command -v zip >/dev/null 2>&1; }

make_zip() {
  local name="$1"; local src="$2"; local max="$3"
  local out="$DIST/$name"
  if zip_available; then
    ( cd "$(dirname "$src")" && zip -r -q "$out" "${EXCLUDES[@]}" "$(basename "$src")" )
  else
    python - "$out" "$src" <<'PY'
import shutil, sys, os
out, src = sys.argv[1], sys.argv[2]
shutil.make_archive(out.rsplit('.zip',1)[0], 'zip', os.path.dirname(src), os.path.basename(src))
PY
  fi
  local size
  size=$(stat -c%s "$out" 2>/dev/null || stat -f%z "$out" 2>/dev/null)
  echo "    $name : $((size/1024)) KB"
  if [ "$size" -gt "$max" ]; then
    echo "ERROR: $name 超出大小预算 ($((max/1024/1024))MB): ${size} 字节" >&2
    exit 1
  fi
}

echo "==> 生成分发包"
make_zip "aife-${VERSION}-win-x64.zip"     "$STAGE" "$PLATFORM_MAX"
make_zip "aife-${VERSION}-macos-arm64.zip" "$STAGE" "$PLATFORM_MAX"
make_zip "aife-${VERSION}-linux-x64.zip"   "$STAGE" "$PLATFORM_MAX"
make_zip "aife-${VERSION}-source.zip"     "$STAGE" "$GITHUB_MAX"

# ---- SHA256SUMS ----
echo "==> 生成 SHA256SUMS"
if command -v sha256sum >/dev/null 2>&1; then
  ( cd "$DIST" && sha256sum aife-*.zip ) > "$DIST/SHA256SUMS"
else
  ( cd "$DIST" && for f in aife-*.zip; do python -c "import hashlib,sys;print(hashlib.sha256(open('$f','rb').read()).hexdigest(),'$f')"; done ) > "$DIST/SHA256SUMS"
fi
cat "$DIST/SHA256SUMS"

echo "==> 完成。产物位于 $DIST"
ls -la "$DIST"
