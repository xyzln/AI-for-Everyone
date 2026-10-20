# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for AIE desktop window build (onedir, no console, app icon).
# Run from repo root:
#   pyinstaller packaging/aife_desktop.spec --noconfirm \
#       --distpath dist/pyinstaller-desktop --workpath build/pyinstaller-desktop
#
# 与 aife.spec 的差异：console=False（GUI 应用）、exe 图标、entry 无参默认
# desktop（packaging/aife_entry.py），并 collect_all('pywebview') 把其私有
# 数据/二进制（WebView2 .NET 装配体与原生 Loader）收进包。
import os
import sys

ROOT = os.path.abspath(os.path.join(os.getcwd(), os.path.dirname(SPECPATH)))

block_cipher = None


def _pick_icon():
    """按平台选择 exe/app 图标；缺失则返回 None（PyInstaller 允许无图标）。"""
    if sys.platform == "darwin":
        p = os.path.join(ROOT, "aife", "assets", "icon.icns")
    elif sys.platform.startswith("linux"):
        p = os.path.join(ROOT, "aife", "assets", "icon.png")
    else:
        p = os.path.join(ROOT, "aife", "assets", "icon.ico")
    return p if os.path.exists(p) else None

# 数据文件：Web UI 静态资源 + 配置模板 + 托盘/窗口图标（运行时读取）
datas = [
    (os.path.join(ROOT, "web"), "web"),
    (os.path.join(ROOT, "config", "aife.yaml"), "config"),
    (os.path.join(ROOT, "aife", "assets"), "aife/assets"),
]

# pywebview 私有数据/二进制（webview/lib 下的 WebView2 装配体与 Loader DLL）
from PyInstaller.utils.hooks import collect_all  # noqa: E402

pv_datas, pv_binaries, pv_hiddenimports = collect_all("pywebview")

# uvicorn 通过字符串导入 app；显式声明，避免打包遗漏（与 aife.spec 保持一致）。
hiddenimports = [
    "aife",
    "aife.cli",
    "aife.config",
    "aife.runtime",
    "aife.bootstrap",
    "aife.hardware",
    "aife.desktop",
    "aife.server.app",
    "aife.server.ws",
    "aife.server.errors",
    "aife.server.deps",
    "aife.server.sse",
    "aife.server.routes",
    "aife.server.routes.health",
    "aife.server.routes.system",
    "aife.server.routes.models",
    "aife.server.routes.chat",
    "aife.server.routes.backends",
    "aife.server.routes.setup",
    "aife.server.routes.ollama",
    "aife.server.routes.v1_openai",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "websockets",
    "yaml",
    # 托盘（可选依赖）：desktop.py 惰性 import，PyInstaller 可能扫不到，显式声明
    "pystray",
    "PIL",
    "PIL.Image",
] + pv_hiddenimports

a = Analysis(
    [os.path.join(ROOT, "packaging", "aife_entry.py")],
    pathex=[ROOT],
    binaries=pv_binaries,
    datas=datas + pv_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pytest", "IPython"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="aife",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                       # 窗口版：无控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_pick_icon(),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="aife",
)

# macOS：产出 .app 捆绑包（图标用 .icns；缺失则无图标）
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="AIE.app",
        icon=_pick_icon(),
        bundle_identifier="cn.aife.desktop",
    )
