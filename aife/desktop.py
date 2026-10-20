"""Native desktop window shell (pywebview) with tray + browser fallback.

Wraps the existing Web UI in a native window (Windows: system Edge WebView2 —
no separate browser needed). ``pywebview`` and ``pystray`` are **optional**
dependencies, imported lazily inside the functions so the CLI stays importable
without them. Any failure (missing dependency, WebView2 runtime absent, window
creation error) falls back to ``webbrowser.open`` — never worse than the
previous "open a browser" behavior (02-architecture §5.4). A missing pystray
only skips the tray; window behavior is unchanged.

Threading model: the embedded uvicorn server runs in a dedicated thread with
its own event loop, because ``webview.start()`` blocks on the native GUI
message loop — sharing one event loop would starve the server and the page
would never load. The GUI runs on the main thread (required by the Windows
backend; pythonnet/WinForms). The tray icon runs in its own daemon thread
(pystray's message loop).
"""

from __future__ import annotations

import asyncio
import threading
import time
import webbrowser
from typing import TYPE_CHECKING, Optional

from .utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注，避免运行期循环导入
    from .config import DesktopConfig
    from .runtime import Runtime

logger = get_logger("aife.desktop")

_WINDOW_TITLE = "AI For Everyone"
_WINDOW_SIZE = (1280, 860)
_WINDOW_MIN_SIZE = (960, 640)
_SERVER_READY_TIMEOUT_S = 30.0
_SERVER_STOP_TIMEOUT_S = 10.0
_TRAY_ICON_RELPATH = ("aife", "assets", "icon.ico")
_FALLBACK_HINT = (
    "未能创建原生窗口，已回退用浏览器打开（可安装 WebView2 运行时以获得窗口体验）"
)


def _browse_host(host: str) -> str:
    """``0.0.0.0``/``::`` 监听全部网卡，但窗口与浏览器应走回环地址。"""
    return "127.0.0.1" if host in ("0.0.0.0", "::", "") else host


def _url(host: str, port: int) -> str:
    return f"http://{_browse_host(host)}:{port}/"


async def _start_embedded_server(app, host: str, port: int, log_level: str):
    """在后台线程运行 uvicorn，就绪后返回 ``(server, thread)``。

    ``webview.start()`` 会阻塞主线程的 GUI 消息循环，因此服务必须跑在独立
    线程的独立事件循环里，否则页面永远加载不出来。
    """
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(
        app, host=host, port=port, log_level=log_level, access_log=False,
    ))

    def _serve() -> None:
        asyncio.run(server.serve())

    thread = threading.Thread(target=_serve, name="aife-embedded-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + _SERVER_READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if server.started:
            logger.info("embedded server started",
                        fields={"url": f"http://{host}:{port}"})
            return server, thread
        if not thread.is_alive():
            raise RuntimeError("内嵌服务启动失败（端口可能已被占用）")
        await asyncio.sleep(0.05)
    server.should_exit = True
    raise RuntimeError(f"内嵌服务启动超时（{_SERVER_READY_TIMEOUT_S:.0f}s）")


# --------------------------------------------------------------------------- #
# Tray (optional: pystray + Pillow; missing -> silently skipped)
# --------------------------------------------------------------------------- #
def _start_tray(url: str, toggle_cb, quit_cb):
    """启动系统托盘图标；pystray 缺失/图标缺失/任何失败均返回 None。"""
    try:
        import pystray
        from PIL import Image

        from .utils.paths import resource_root

        icon_path = resource_root().joinpath(*_TRAY_ICON_RELPATH)
        if not icon_path.exists():
            logger.warning("tray icon missing, tray disabled",
                           fields={"path": str(icon_path)})
            return None
        image = Image.open(icon_path)
        menu = pystray.Menu(
            pystray.MenuItem("显示/隐藏", lambda _icon, _item: toggle_cb(), default=True),
            pystray.MenuItem("在浏览器打开", lambda _icon, _item: webbrowser.open(url)),
            pystray.MenuItem("退出", lambda _icon, _item: quit_cb()),
        )
        tray = pystray.Icon("AIE", image, _WINDOW_TITLE, menu)
        threading.Thread(target=tray.run, name="aife-tray", daemon=True).start()
        logger.info("tray started", fields={"icon": str(icon_path)})
        return tray
    except Exception as exc:
        logger.warning("tray unavailable, continuing without tray",
                       fields={"error": str(exc)})
        return None


def _toggle_window(win, state: dict[str, bool]) -> None:
    """托盘"显示/隐藏"：按我们跟踪的可见性切换（pywebview 无 is_visible 属性）。"""
    if state["visible"]:
        state["visible"] = False
        win.hide()
    else:
        state["visible"] = True
        win.show()
        win.restore()


def _quit_window(win) -> None:
    try:
        win.destroy()
    except Exception:  # pragma: no cover - 已退出时的兜底
        pass


def _wire_window_events(win, desktop_cfg: "DesktopConfig", state: dict[str, bool]) -> None:
    """最小化到托盘（配置开启时）；事件 API 缺失则静默跳过。"""
    events = getattr(win, "events", None)
    if events is None:
        return

    def _on_minimized() -> None:
        if desktop_cfg.minimize_to_tray:
            state["visible"] = False
            win.hide()

    def _on_restored() -> None:
        state["visible"] = True

    for name, handler in (("minimized", _on_minimized), ("restored", _on_restored)):
        try:
            event = getattr(events, name)
            event += handler  # Event.__iadd__ 注册回调并返回自身
        except Exception:  # pragma: no cover - 后端事件差异
            logger.debug("window event unavailable", fields={"event": name})


def _run_native_window(url: str, title: str, use_tray: bool,
                       desktop_cfg: "DesktopConfig") -> None:
    """创建窗口、接线事件与托盘、阻塞运行 GUI 直到窗口关闭。失败抛异常。"""
    import webview  # 惰性 import：可选依赖缺失即回退浏览器

    win = webview.create_window(
        title, url=url,
        width=_WINDOW_SIZE[0], height=_WINDOW_SIZE[1],
        min_size=_WINDOW_MIN_SIZE,
    )
    state = {"visible": True}
    _wire_window_events(win, desktop_cfg, state)
    tray = (
        _start_tray(url, lambda: _toggle_window(win, state),
                    lambda: _quit_window(win))
        if use_tray else None
    )
    try:
        webview.start()
    finally:
        if tray is not None:
            try:
                tray.stop()
            except Exception:  # pragma: no cover - 已停止时的兜底
                pass


def _stop_server(server, thread: threading.Thread) -> None:
    """优雅关停内嵌服务（uvicorn lifespan 会顺带调 rt.shutdown）。"""
    server.should_exit = True
    thread.join(_SERVER_STOP_TIMEOUT_S)
    if thread.is_alive():  # pragma: no cover - 兜底强退
        server.force_exit = True
        thread.join(5)


async def run_window(
    rt: "Runtime",
    host: Optional[str] = None,
    port: Optional[int] = None,
    title: str = _WINDOW_TITLE,
    tray: Optional[bool] = None,
) -> None:
    """以原生窗口运行 AIE；窗口关闭或失败后返回。绝不抛到调用方。

    ``tray=None`` 跟随 ``rt.cfg.desktop.tray``；显式 True/False 覆盖配置
    （CLI ``--no-tray`` 传 False）。
    """
    host = host or rt.cfg.server.host
    port = port or rt.cfg.server.port
    url = _url(host, port)
    use_tray = rt.cfg.desktop.tray if tray is None else tray

    from .server.app import app  # 复用同一 app 与 runtime 单例

    print(f"AIE 桌面窗口启动中: {url}")
    server, thread = await _start_embedded_server(
        app, host, port, rt.cfg.server.log_level
    )

    native = False
    try:
        _run_native_window(url, title, use_tray, rt.cfg.desktop)
        native = True
    except Exception as exc:
        logger.warning("native window unavailable, falling back to browser",
                       fields={"error": str(exc)})
        print(f"{_FALLBACK_HINT}: {url}")

    if native:
        print("窗口已关闭，正在停止 AIE 服务...")
        _stop_server(server, thread)
    else:
        # 回退浏览器：保持服务运行直到用户中断（与 serve 行为一致）
        try:
            webbrowser.open(url)
        except Exception:  # pragma: no cover - 无可用浏览器时不崩
            pass
        try:
            while thread.is_alive():
                await asyncio.sleep(0.5)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n正在停止 AIE 服务...")
        _stop_server(server, thread)

    # 防御性二次关停：lifespan 通常已执行 rt.shutdown()；跨线程异常忽略
    try:
        await rt.shutdown()
    except Exception:  # pragma: no cover - defensive
        pass
    print("AIE 已退出。")
