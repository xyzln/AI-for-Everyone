# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for AIE standalone (onedir). Run from repo root:
#   pyinstaller packaging/aife.spec --noconfirm --distpath dist/pyinstaller --workpath build/pyinstaller
import os

ROOT = os.path.abspath(os.path.join(os.getcwd(), os.path.dirname(SPECPATH)))

block_cipher = None

# 数据文件：Web UI 静态资源 + 配置模板
datas = [
    (os.path.join(ROOT, "web"), "web"),
    (os.path.join(ROOT, "config", "aife.yaml"), "config"),
]

# uvicorn 通过字符串导入 app；显式声明，避免打包遗漏。
hiddenimports = [
    "aife",
    "aife.cli",
    "aife.config",
    "aife.runtime",
    "aife.bootstrap",
    "aife.hardware",
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
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "websockets",
    "yaml",
]

a = Analysis(
    [os.path.join(ROOT, "packaging", "aife_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
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
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
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
