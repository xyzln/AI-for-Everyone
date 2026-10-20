"""WebSocket endpoint tests: cancellation must end quietly (no ERROR noise).

uvicorn cancels the ASGI task on graceful shutdown; ``asyncio.CancelledError``
inherits ``BaseException`` so an ``except Exception`` does not catch it — it
would escape and be logged as ``ERROR: Exception in ASGI application`` with a
full traceback. These tests pin the quiet-shutdown contract and normal event
delivery (snapshot + bus events).
"""

import asyncio

from fastapi import WebSocketDisconnect

from aife.server.ws import mgr, ws_events


class _FakeWS:
    """Minimal WebSocket stand-in for the handler's call pattern."""

    def __init__(self):
        self.accepted = False
        self.sent: list[dict] = []
        self.closed = False
        self._silent = asyncio.Event()  # 客户端静默：receive 永挂起

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        self.sent.append(data)

    async def receive(self):
        await self._silent.wait()

    async def close(self):
        self.closed = True


class _DisconnectingWS(_FakeWS):
    """客户端已消失：receive 立刻抛 WebSocketDisconnect（starlette 语义）。"""

    async def receive(self):
        raise WebSocketDisconnect(1005)


def _run_ws(ws, rt, *, cancel_after_s=0.05, publish=None):
    async def _run():
        task = asyncio.create_task(ws_events(ws))
        await asyncio.sleep(cancel_after_s)
        if publish is not None:
            rt.publish(*publish)
            await asyncio.sleep(0.1)
        task.cancel()
        # 关键断言：被取消的任务不得把 CancelledError 抛出来
        # （裸抛 = uvicorn 记 ERROR traceback）。静默吞掉则 await 正常返回。
        await task

    asyncio.run(_run())
    return ws


def test_ws_cancel_ends_quietly(runtime):
    ws = _FakeWS()
    _run_ws(ws, runtime)
    assert ws.accepted is True
    # 首帧 snapshot 仍发出；finally 退订生效（不在连接集合里）
    assert ws.sent and ws.sent[0]["type"] == "snapshot"
    assert ws not in mgr.clients


def test_ws_exits_promptly_on_client_disconnect(runtime):
    """客户端消失（浏览器被杀）时 handler 必须自行退出。

    否则 ASGI 任务永驻 → uvicorn 优雅关停等超时走 force_exit → 跳过
    lifespan.shutdown → 拆循环时取消 lifespan 任务打出 ERROR traceback。
    """
    ws = _DisconnectingWS()

    async def run():
        task = asyncio.create_task(ws_events(ws))
        await asyncio.sleep(0.1)
        assert task.done(), "客户端断开后 handler 应及时退出"
        assert task.exception() is None  # WebSocketDisconnect 不得逃逸

    asyncio.run(run())
    assert ws not in mgr.clients


def test_ws_delivers_bus_events(runtime):
    ws = _FakeWS()
    _run_ws(ws, runtime, publish=("test.ping", {"x": 1}))
    types = [m["type"] for m in ws.sent]
    assert "snapshot" in types
    assert "test.ping" in types


def test_ws_heartbeat_on_idle(runtime):
    # 心跳间隔压到 1s 下限，空闲时应自发 heartbeat
    runtime.cfg.server.ws_heartbeat_s = 1.0
    ws = _FakeWS()

    async def _run():
        task = asyncio.create_task(ws_events(ws))
        await asyncio.sleep(1.3)
        task.cancel()
        await task

    asyncio.run(_run())
    assert any(m["type"] == "heartbeat" for m in ws.sent)
