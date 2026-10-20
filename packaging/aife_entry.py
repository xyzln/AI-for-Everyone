"""Standalone launcher entry (PyInstaller).

双击运行（无参数）时默认启动原生桌面窗口（pywebview 包现有 Web UI；不可用时
自动回退浏览器打开）；带参数时透传给 aife CLI。
首次运行会确保生成 ~/.aife/config.yaml。
"""

import sys


def _bootstrap() -> int:
    # 确保用户级配置存在（从内置模板复制）
    try:
        from aife.config import ensure_config
        ensure_config()
    except Exception:
        pass

    from aife.cli import main
    argv = sys.argv[1:]
    if not argv:
        # 无参数 = 双击启动：原生桌面窗口（缺 pywebview 时 desktop 自行回退浏览器）
        argv = ["desktop"]
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(_bootstrap())