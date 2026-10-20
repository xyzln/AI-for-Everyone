"""Chat endpoints: non-streaming + SSE streaming (02-architecture §5.2, 05 §5.4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...errors import AIEError, ErrorCode
from ...runtime import Runtime
from ..deps import get_rt
from ..schemas import ChatMessage, ChatRequest, ChatResponse
from ..sse import sse_pack

router = APIRouter(tags=["chat"])


def _require_backend(rt: Runtime):
    backend = rt.registry.current()
    if backend is None:
        raise AIEError(ErrorCode.BACKEND_UNHEALTHY, "无活跃的推理后端")
    return backend


def _messages(body: ChatRequest):
    return [m.model_dump() for m in body.messages]


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, rt: Runtime = Depends(get_rt)) -> ChatResponse:
    backend = _require_backend(rt)
    st = await backend.health()
    if not st.healthy:
        raise AIEError(ErrorCode.BACKEND_UNHEALTHY, st.detail or "后端不可用")
    content = ""
    usage = None
    async for ev in backend.chat(
        model=body.model, messages=_messages(body), options=body.options, stream=False
    ):
        if ev.get("delta"):
            content += ev["delta"]
        if ev.get("usage") is not None:
            usage = ev["usage"]
    return ChatResponse(message=ChatMessage(role="assistant", content=content), usage=usage)


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, rt: Runtime = Depends(get_rt)) -> StreamingResponse:
    backend = _require_backend(rt)

    async def _gen():
        try:
            st = await backend.health()
            if not st.healthy:
                yield sse_pack("error", {"code": ErrorCode.BACKEND_UNHEALTHY.value,
                                        "message": st.detail or "后端不可用"})
                return
            async for ev in backend.chat(
                model=body.model, messages=_messages(body), options=body.options, stream=True
            ):
                if ev.get("delta"):
                    yield sse_pack("delta", {"delta": ev["delta"]})
                if ev.get("usage") is not None:
                    yield sse_pack("usage", ev["usage"])
                if ev.get("done"):
                    yield sse_pack("done", {})
        except AIEError as exc:
            yield sse_pack("error", {"code": exc.code.value, "message": exc.message})
        except Exception as exc:  # pragma: no cover
            yield sse_pack("error", {"code": "INTERNAL_ERROR", "message": str(exc)})

    return StreamingResponse(_gen(), media_type="text/event-stream")
