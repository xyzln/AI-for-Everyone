"""OpenAI-compatible surface at ``/v1/*`` (D21/D22, ADR-006).

Exposes the two endpoints every OpenAI client expects — ``GET /v1/models`` and
``POST /v1/chat/completions`` (streaming SSE + non-streaming) — on top of the
internal backend registry. The router is mounted **without** the ``/api``
prefix; request/response models are pydantic so the exported OpenAPI stays
complete.

Error contract differs from ``/api/*`` by design (D22): errors here use the
OpenAI envelope ``{"error": {"message", "type", "code", "param"}}`` while
``/api/*`` keeps the unified ``{"error": {code, message, details, trace_id}}``.
``register_v1_error_handlers`` installs path-aware handlers so the two never
mix: only ``/v1`` paths get the OpenAI envelope, everything else delegates to
the handlers registered by ``aife.server.errors``.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from ...errors import AIEError, ErrorCode
from ...ollama.protocol import OllamaProtocolError
from ...runtime import Runtime
from ...utils.logging import get_logger
from ..deps import get_rt

logger = get_logger("aife.server.routes.v1_openai")

router = APIRouter(tags=["openai-compat"])

_OPENAI_PREFIX = "/v1"

# OpenAI 错误类型（D22）
_TYPE_INVALID = "invalid_request_error"
_TYPE_SERVER = "server_error"
_TYPE_RATE = "rate_limit_error"


# --------------------------------------------------------------------------- #
# Schemas (pydantic v2 — OpenAPI 完整导出，ADR-006)
# --------------------------------------------------------------------------- #
class V1ChatMessage(BaseModel):
    role: str
    content: str


class V1ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: list[V1ChatMessage] = Field(default_factory=list)
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None


class V1ModelCard(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "aife"


class V1ModelsResponse(BaseModel):
    object: str = "list"
    data: list[V1ModelCard] = Field(default_factory=list)


class V1Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class V1Delta(BaseModel):
    content: Optional[str] = None


class V1ResponseMessage(BaseModel):
    role: str = "assistant"
    content: str


class V1Choice(BaseModel):
    index: int = 0
    message: V1ResponseMessage
    finish_reason: Optional[str] = "stop"


class V1ChunkChoice(BaseModel):
    index: int = 0
    delta: V1Delta
    finish_reason: Optional[str] = None


class V1ChatCompletion(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[V1Choice]
    usage: Optional[V1Usage] = None


class V1ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[V1ChunkChoice] = Field(default_factory=list)
    usage: Optional[V1Usage] = None


class V1ErrorBody(BaseModel):
    """OpenAI 错误信封（D22）。"""

    message: str
    type: str
    code: Optional[str] = None
    param: Optional[str] = None


class V1ErrorResponse(BaseModel):
    error: V1ErrorBody


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _error_type_for_status(status: int) -> str:
    if status == 429:
        return _TYPE_RATE
    if status >= 500:
        return _TYPE_SERVER
    return _TYPE_INVALID


def _openai_error(
    status: int,
    message: str,
    *,
    code: Optional[str] = None,
    param: Optional[str] = None,
    type_: Optional[str] = None,
) -> JSONResponse:
    body = V1ErrorResponse(
        error=V1ErrorBody(
            message=message,
            type=type_ or _error_type_for_status(status),
            code=code,
            param=param,
        )
    )
    return JSONResponse(status_code=status, content=body.model_dump())


def _sse_data(obj: BaseModel) -> str:
    """One SSE frame: ``data: {json}\\n\\n``（无 event 行，OpenAI 约定）。"""
    return f"data: {json.dumps(obj.model_dump(), ensure_ascii=False)}\n\n"


def _norm_usage(usage: Optional[dict[str, Any]]) -> Optional[V1Usage]:
    if not usage:
        return None
    pt = int(usage.get("prompt_tokens", 0) or 0)
    ct = int(usage.get("completion_tokens", 0) or 0)
    total = usage.get("total_tokens")
    return V1Usage(
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=int(total) if total is not None else pt + ct,
    )


def _backend_default_model(backend: Any) -> str:
    """活跃后端的默认/配置模型名（用于 model 缺省与 /v1/models 兜底）。"""
    fn = getattr(backend, "default_model", None)
    if callable(fn):
        model = fn()
        if model:
            return model
    return getattr(getattr(backend, "section", None), "model", "") or ""


async def _active_model_ids(rt: Runtime) -> list[str]:
    backend = rt.registry.current()
    if backend is None:
        return []
    if backend.name == "ollama":
        try:
            names = [m.name for m in await rt.model_manager.list_installed() if m.name]
        except AIEError:
            names = []
        default = rt.cfg.models.default
        if default and default not in names:
            names.append(default)  # 至少暴露活跃后端默认模型
        return names
    # 其它后端：其配置模型（llamacpp/vllm/openai_compat 均有 model 字段）
    model = getattr(getattr(rt.cfg, backend.name, None), "model", "") or ""
    return [model] if model else []


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@router.get("/models", response_model=V1ModelsResponse)
async def list_models(rt: Runtime = Depends(get_rt)) -> V1ModelsResponse:
    ids = await _active_model_ids(rt)
    created = int(time.time())
    return V1ModelsResponse(
        data=[V1ModelCard(id=m, created=created, owned_by="aife") for m in ids]
    )


@router.post(
    "/chat/completions",
    response_model=V1ChatCompletion,
    responses={
        400: {"model": V1ErrorResponse},
        503: {"model": V1ErrorResponse},
        500: {"model": V1ErrorResponse},
    },
)
async def chat_completions(body: V1ChatRequest, rt: Runtime = Depends(get_rt)):
    try:
        if not body.messages:
            raise AIEError(ErrorCode.VALIDATION, "messages 不可为空")
        backend = rt.registry.current()
        if backend is None:
            raise AIEError(ErrorCode.BACKEND_UNHEALTHY, "无活跃的推理后端")
        st = await backend.health()
        if not st.healthy:
            raise AIEError(ErrorCode.BACKEND_UNHEALTHY, st.detail or "后端不可用")
        model = body.model or _backend_default_model(backend)
        messages = [m.model_dump() for m in body.messages]
        options = {
            "temperature": body.temperature,
            "top_p": body.top_p,
            "max_tokens": body.max_tokens,
        }
        if body.stream:
            return _stream_response(backend, model, messages, options)
        content, usage = await _collect(backend, model, messages, options)
        return V1ChatCompletion(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            created=int(time.time()),
            model=model,
            choices=[V1Choice(message=V1ResponseMessage(content=content))],
            usage=_norm_usage(usage),
        )
    except AIEError as exc:
        return _openai_error(exc.status_code, exc.message, code=exc.code.value)
    except OllamaProtocolError as exc:
        return _openai_error(503, str(exc), code="backend_unavailable")
    except Exception as exc:  # pragma: no cover - defensive
        trace = uuid.uuid4().hex
        logger.error("v1 chat failed", fields={"error": str(exc)}, event="error",
                     trace_id=trace)
        return _openai_error(500, "服务内部出错", code="internal_error")


async def _collect(backend, model: str, messages: list[dict[str, str]],
                   options: dict[str, Any]) -> tuple[str, Optional[dict[str, Any]]]:
    parts: list[str] = []
    usage: Optional[dict[str, Any]] = None
    async for ev in backend.chat(model=model, messages=messages, options=options,
                                 stream=False):
        if ev.get("delta"):
            parts.append(ev["delta"])
        if ev.get("usage") is not None:
            usage = ev["usage"]
    return "".join(parts), usage


def _stream_response(backend, model: str, messages: list[dict[str, str]],
                     options: dict[str, Any]) -> StreamingResponse:
    cmpl_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    async def _gen():
        try:
            async for ev in backend.chat(model=model, messages=messages,
                                         options=options, stream=True):
                if ev.get("delta"):
                    yield _sse_data(V1ChatCompletionChunk(
                        id=cmpl_id, created=created, model=model,
                        choices=[V1ChunkChoice(delta=V1Delta(content=ev["delta"]))],
                    ))
                if ev.get("usage") is not None:
                    yield _sse_data(V1ChatCompletionChunk(
                        id=cmpl_id, created=created, model=model,
                        choices=[], usage=_norm_usage(ev["usage"]),
                    ))
                if ev.get("done"):
                    break
        except Exception as exc:  # 流已开始：错误只能以 SSE 帧传达
            logger.warning("v1 stream failed", fields={"error": str(exc)})
            yield _sse_data(V1ErrorResponse(
                error=V1ErrorBody(message=str(exc), type=_TYPE_SERVER,
                                  code="stream_error")
            ))
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
# Error handlers (D22): /v1 用 OpenAI 信封，其它路径委托既有统一处理器
# --------------------------------------------------------------------------- #
def _openai_from_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    errs = exc.errors()
    first = errs[0] if errs else {}
    loc = [str(x) for x in first.get("loc", ()) if x not in ("body",)]
    return _openai_error(
        400,
        first.get("msg", "请求内容没有通过校验"),
        code="invalid_request",
        param=".".join(loc) or None,
    )


def _openai_from_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _openai_error(exc.status_code, str(exc.detail or ""))


def _openai_from_aie(_: Request, exc: AIEError) -> JSONResponse:
    return _openai_error(exc.status_code, exc.message, code=exc.code.value)


def _openai_from_unhandled(request: Request, exc: Exception) -> JSONResponse:
    trace = uuid.uuid4().hex
    logger.error("unhandled exception on /v1", fields={"error": str(exc)},
                 event="error", trace_id=trace)
    return _openai_error(500, "服务内部出错", code="internal_error")


def register_v1_error_handlers(app) -> None:
    """Wrap the unified handlers with a path check.

    Must be called **after** ``register_error_handlers`` so the previous
    handlers can be captured and delegated to for non-``/v1`` paths.
    """
    wrappers = (
        (RequestValidationError, _openai_from_validation),
        (StarletteHTTPException, _openai_from_http),
        (AIEError, _openai_from_aie),
        (Exception, _openai_from_unhandled),
    )
    for exc_cls, builder in wrappers:
        prev = app.exception_handlers.get(exc_cls)

        def _make(builder=builder, prev=prev):
            async def _handler(request: Request, exc):
                if request.url.path.startswith(_OPENAI_PREFIX):
                    return builder(request, exc)
                if prev is not None:
                    return await prev(request, exc)
                raise exc  # pragma: no cover - 理论上不会到达

            return _handler

        app.exception_handler(exc_cls)(_make())
