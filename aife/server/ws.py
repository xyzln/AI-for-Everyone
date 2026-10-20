"""WebSocket event bus — fans out runtime events to browser clients (05 §5.3).

Clients connect to ``/ws/events`` (single connection, full broadcast). The server
sends a 30s heartbeat. Events come from the runtime event bus (domain layer
publishes; this adapter subscribes and forwards). No import dependency from domain
→ server (architecture §1.3 R4) — the bus is injected by reference.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..runtime import get_runtime
from ..utils.logging import get_logger

logger = get_logger("aife.server.ws")

router = APIRouter()


class WSConnectionManager:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def send(self, ws: WebSocket, event: dict[str, Any]) -> None:
        try:
            await ws.send_json(event)
        except Exception:
            self.disconnect(ws)


mgr = WSConnectionManager()


async def _drain_receive(ws: WebSocket) -> None:
    """持续消费接收通道；收到断开消息时抛 ``WebSocketDisconnect``。

    UI 不往 ``/ws/events`` 发消息，但没有这个任务，handler 在客户端消失
    （含浏览器进程被杀）后仍永远挂在事件队列上——ASGI 任务不结束，
    uvicorn 优雅关停必然等超时走 ``force_exit``，跳过 ``lifespan.shutdown``
    并在拆事件循环时把 lifespan 任务取消成 ERROR traceback。

    注意：starlette 的 ``receive()`` 对断开消息只返回不抛异常（抛断异常的
    是 ``receive_text/json`` 系列），所以这里显式转换。
    """
    while True:
        message = await ws.receive()
        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    rt = get_runtime()
    await ws.accept()
    await mgr.connect(ws)
    queue: asyncio.Queue = asyncio.Queue()

    def _on_event(event: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_event_loop()
            loop.call_soon(queue.put_nowait, event)
        except Exception:  # pragma: no cover
            pass

    unsub = rt.bus.subscribe(_on_event)
    heartbeat_s = max(1.0, rt.cfg.server.ws_heartbeat_s)
    recv_task: Optional[asyncio.Task] = None
    get_task: Optional[asyncio.Task] = None
    try:
        # initial snapshot so the UI has data immediately
        from .schemas import SystemInfo
        await ws.send_json({
            "type": "snapshot", "ts": "", "payload": {
                "profile": rt.resolved.profile_id,
                "active_backend": rt.registry.active,
            },
        })
        recv_task = asyncio.create_task(_drain_receive(ws))
        while True:
            # race: 事件到达 / 客户端断开 / 心跳超时，谁先来都算
            get_task = asyncio.ensure_future(queue.get())
            done, _pending = await asyncio.wait(
                {get_task, recv_task},
                timeout=heartbeat_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if get_task in done:
                await mgr.send(ws, get_task.result())
            else:
                get_task.cancel()
                from datetime import datetime, timezone
                hb = {
                    "type": "heartbeat",
                    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "payload": {},
                }
                await mgr.send(ws, hb)
            if recv_task in done:
                if not get_task.done():
                    get_task.cancel()
                recv_task.result()  # 断开 → WebSocketDisconnect 抛给外层
                recv_task = asyncio.create_task(_drain_receive(ws))
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        # 关停时 uvicorn 会取消本任务：CancelledError 继承 BaseException，
        # 不会被下面的 except Exception 捕获，裸抛出去会被 uvicorn 记成
        # ERROR + 全栈 traceback。优雅关停是正常路径，静默吞掉即可
        # （finally 里的退订/断开照常执行）。
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("ws loop ended", fields={"error": str(exc)})
    finally:
        for task in (recv_task, get_task):
            if task is not None and not task.done():
                task.cancel()
        unsub()
        mgr.disconnect(ws)
