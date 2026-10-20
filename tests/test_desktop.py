"""Desktop window shell tests (pywebview/pystray optional, browser fallback).

No real GUI / uvicorn / tray: ``_run_native_window`` and ``_start_embedded_server``
are stubbed, and optional imports are forced to fail via ``sys.modules``.
Proves the orchestration: fallback opens the browser and still shuts down
cleanly; native path stops the embedded server; tray wiring degrades silently.
"""

import asyncio
import sys
import webbrowser

import pytest

import aife.desktop as desktop
from aife.cli import _build_parser
from aife.config import DesktopConfig, load_config
from aife.runtime import Runtime


class _FakeServer:
    started = True

    def __init__(self):
        self.should_exit = False
        self.force_exit = False


class _FakeThread:
    def __init__(self):
        self.joined = []

    def is_alive(self):
        return False

    def join(self, timeout=None):
        self.joined.append(timeout)


class _FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for h in self.handlers:
            h()


class _FakeWindow:
    def __init__(self):
        self.events = type("E", (), {
            "minimized": _FakeEvent(), "restored": _FakeEvent(),
        })()
        self.hidden = False
        self.destroyed = False
        self.shown = 0
        self.restored = 0

    def hide(self):
        self.hidden = True

    def show(self):
        self.shown += 1
        self.hidden = False

    def restore(self):
        self.restored += 1

    def destroy(self):
        self.destroyed = True


class _FakeTray:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def _runtime(**desktop_overrides) -> Runtime:
    cfg = load_config()
    cfg.server.port = 18189  # 避开常用端口，防与真实服务冲突
    for k, v in desktop_overrides.items():
        setattr(cfg.desktop, k, v)
    return Runtime(cfg)


def _patch_start(monkeypatch, server, thread, calls):
    async def _fake_start(app, host, port, log_level):
        calls.append({"host": host, "port": port, "log_level": log_level})
        return server, thread

    monkeypatch.setattr(desktop, "_start_embedded_server", _fake_start)


def _patch_shutdown(monkeypatch, rt, calls):
    async def _fake_shutdown():
        calls.append("shutdown")

    monkeypatch.setattr(rt, "shutdown", _fake_shutdown)


# ---- browser fallback -------------------------------------------------------- #
def test_run_window_falls_back_to_browser(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", None)  # 模拟 pywebview 缺失
    server, thread = _FakeServer(), _FakeThread()
    start_calls, shutdown_calls = [], []
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    rt = _runtime()
    _patch_start(monkeypatch, server, thread, start_calls)
    _patch_shutdown(monkeypatch, rt, shutdown_calls)

    asyncio.run(desktop.run_window(rt))

    # 回退：浏览器被打开、服务被关停、runtime 被关闭
    assert opened == [f"http://127.0.0.1:{rt.cfg.server.port}/"]
    assert server.should_exit is True
    assert thread.joined  # join 过
    assert shutdown_calls == ["shutdown"]
    # host/port 缺省取 cfg.server
    assert start_calls[0]["host"] == rt.cfg.server.host
    assert start_calls[0]["port"] == rt.cfg.server.port
    assert start_calls[0]["log_level"] == rt.cfg.server.log_level


def test_run_window_falls_back_when_window_raises(monkeypatch):
    # pywebview 存在但建窗/start 抛错（如缺 WebView2 运行时）→ 同样回退
    def _boom(url, title, use_tray, desktop_cfg):
        raise RuntimeError("WebView2 runtime missing")

    monkeypatch.setattr(desktop, "_run_native_window", _boom)
    server, thread = _FakeServer(), _FakeThread()
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    rt = _runtime()
    _patch_start(monkeypatch, server, thread, [])
    _patch_shutdown(monkeypatch, rt, [])

    asyncio.run(desktop.run_window(rt, host="127.0.0.1", port=18999))

    assert opened == ["http://127.0.0.1:18999/"]
    assert server.should_exit is True


# ---- native path ------------------------------------------------------------- #
def test_run_window_native_path_shuts_down(monkeypatch):
    calls = {"native": []}
    monkeypatch.setattr(desktop, "_run_native_window",
                        lambda url, title, use_tray, cfg: calls["native"].append(
                            (url, title, use_tray)))
    server, thread = _FakeServer(), _FakeThread()
    shutdown_calls = []
    rt = _runtime()
    _patch_start(monkeypatch, server, thread, [])
    _patch_shutdown(monkeypatch, rt, shutdown_calls)
    monkeypatch.setattr(webbrowser, "open",
                        lambda url: pytest.fail("native 成功不应打开浏览器"))

    asyncio.run(desktop.run_window(rt, host="0.0.0.0", port=18998, title="T"))

    # 窗口“关闭”后：优雅关停 + 二次 rt.shutdown 防御；0.0.0.0→回环地址
    assert calls["native"] == [("http://127.0.0.1:18998/", "T", True)]
    assert server.should_exit is True
    assert thread.joined
    assert shutdown_calls == ["shutdown"]


def test_run_window_no_tray_overrides_config(monkeypatch):
    calls = {"native": []}
    monkeypatch.setattr(desktop, "_run_native_window",
                        lambda url, title, use_tray, cfg: calls["native"].append(use_tray))
    server, thread = _FakeServer(), _FakeThread()
    rt = _runtime(tray=True)  # 配置开托盘，但调用方显式关
    _patch_start(monkeypatch, server, thread, [])
    _patch_shutdown(monkeypatch, rt, [])

    asyncio.run(desktop.run_window(rt, tray=False))

    assert calls["native"] == [False]  # 显式 False 覆盖配置 True


# ---- tray helpers ------------------------------------------------------------- #
def test_start_tray_returns_none_when_pystray_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "pystray", None)
    assert desktop._start_tray("http://x/", lambda: None, lambda: None) is None


def test_start_tray_returns_none_when_icon_missing(monkeypatch, tmp_path):
    import pystray  # noqa: F401 - 确认真实存在，仅图标路径缺失
    from aife.utils import paths

    monkeypatch.setattr(paths, "resource_root", lambda: tmp_path)
    assert desktop._start_tray("http://x/", lambda: None, lambda: None) is None


def test_start_tray_starts_thread_with_menu(monkeypatch, tmp_path):
    """pystray 可用 + 图标存在：托盘线程启动，Icon 以正确标题/菜单创建。"""
    created = {}

    class _FakeIcon:
        def __init__(self, name, image, title, menu):
            created["args"] = (name, title)
            created["menu"] = menu
            self._stopped = False

        def run(self):  # 在 daemon 线程里被调用；立即返回即可
            created["ran"] = True

        def stop(self):
            self._stopped = True

    class _FakeMenuItem:
        def __init__(self, text, action, default=False):
            self.text, self.action, self.default = text, action, default

    fake_pystray = type(sys)("pystray")
    fake_pystray.Icon = _FakeIcon
    fake_pystray.Menu = lambda *items: list(items)
    fake_pystray.MenuItem = _FakeMenuItem
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)

    from PIL import Image

    class _FakePILImage:
        @staticmethod
        def open(path):
            return object()

    monkeypatch.setattr(Image, "open", _FakePILImage.open)

    from aife.utils import paths

    icon_dir = tmp_path.joinpath(*desktop._TRAY_ICON_RELPATH)
    icon_dir.parent.mkdir(parents=True, exist_ok=True)
    icon_dir.write_bytes(b"ico")
    monkeypatch.setattr(paths, "resource_root", lambda: tmp_path)

    toggled, quit_called = [], []
    tray = desktop._start_tray(
        "http://127.0.0.1:9/", lambda: toggled.append(1), lambda: quit_called.append(1)
    )

    assert tray is not None
    assert created["args"] == ("AIE", "AI For Everyone")
    texts = [item.text for item in created["menu"]]
    assert texts == ["显示/隐藏", "在浏览器打开", "退出"]
    assert created["menu"][0].default is True
    # 菜单动作可达
    created["menu"][0].action(None, None)
    assert toggled == [1]
    created["menu"][2].action(None, None)
    assert quit_called == [1]
    tray.stop()


def test_wire_window_events_minimize_hides(monkeypatch):
    win = _FakeWindow()
    state = {"visible": True}
    desktop._wire_window_events(win, DesktopConfig(minimize_to_tray=True), state)
    win.events.minimized.fire()
    assert win.hidden is True and state["visible"] is False
    win.events.restored.fire()
    assert state["visible"] is True


def test_wire_window_events_disabled_keeps_window(monkeypatch):
    win = _FakeWindow()
    state = {"visible": True}
    desktop._wire_window_events(win, DesktopConfig(minimize_to_tray=False), state)
    win.events.minimized.fire()
    assert win.hidden is False and state["visible"] is True


def test_wire_window_events_missing_events_is_noop():
    class _Bare:
        pass

    desktop._wire_window_events(_Bare(), DesktopConfig(), {"visible": True})  # 不抛


def test_toggle_window(monkeypatch):
    win = _FakeWindow()
    state = {"visible": True}
    desktop._toggle_window(win, state)
    assert win.hidden is True and state["visible"] is False
    desktop._toggle_window(win, state)
    assert win.hidden is False and win.shown == 1 and win.restored == 1
    assert state["visible"] is True


def test_quit_window_destroys():
    win = _FakeWindow()
    desktop._quit_window(win)
    assert win.destroyed is True


# ---- helpers ----------------------------------------------------------------- #
def test_browse_host_maps_wildcard():
    assert desktop._browse_host("0.0.0.0") == "127.0.0.1"
    assert desktop._browse_host("::") == "127.0.0.1"
    assert desktop._browse_host("127.0.0.1") == "127.0.0.1"
    assert desktop._url("0.0.0.0", 8189) == "http://127.0.0.1:8189/"


def test_stop_server_sets_should_exit_and_joins():
    server, thread = _FakeServer(), _FakeThread()
    desktop._stop_server(server, thread)
    assert server.should_exit is True
    assert thread.joined and thread.joined[0] == desktop._SERVER_STOP_TIMEOUT_S


# ---- CLI wiring -------------------------------------------------------------- #
def test_cli_has_desktop_subcommand():
    args = _build_parser().parse_args(["desktop"])
    assert args.command == "desktop"
    assert args.host is None and args.port is None
    assert args.no_tray is False


def test_cli_desktop_no_tray_flag():
    args = _build_parser().parse_args(["desktop", "--no-tray"])
    assert args.no_tray is True


def test_cli_serve_window_flag():
    args = _build_parser().parse_args(["serve", "--window"])
    assert args.window is True
    args = _build_parser().parse_args(["serve"])
    assert args.window is False


# ---- config ------------------------------------------------------------------- #
def test_desktop_config_defaults():
    cfg = load_config()
    assert cfg.desktop.tray is True
    assert cfg.desktop.minimize_to_tray is True


def test_desktop_config_overridable():
    from aife.config import AifeConfig

    cfg = AifeConfig.model_validate({"desktop": {"tray": False, "minimize_to_tray": False}})
    assert cfg.desktop.tray is False
    assert cfg.desktop.minimize_to_tray is False
