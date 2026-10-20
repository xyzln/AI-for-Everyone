"""Unified error handlers — map every exception to the standard error body.

All errors return ``{"error": {"code", "message", "details", "trace_id"}}``
(05-api-contract §3). Crucially: pydantic ``RequestValidationError`` (422) is
rewritten to **400 VALIDATION**, and unhandled exceptions become **500
INTERNAL_ERROR** — never leak a stack trace to the client.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..errors import AIEError, ErrorBody, ErrorResponse
from ..utils.logging import get_logger

logger = get_logger("aife.server.errors")


def _body(code: str, message: str, details=None, trace_id: str = "") -> dict:
    return ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details, trace_id=trace_id)
    ).model_dump()


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AIEError)
    async def _aie(_: Request, exc: AIEError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.code.value, exc.message, exc.details, exc.trace_id),
        )

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=_body("VALIDATION", "请求内容没有通过校验", {"errors": exc.errors()}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            code = "ROUTE_NOT_FOUND"
        else:
            code = f"HTTP_{exc.status_code}"
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(code, exc.detail or "", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        trace = uuid.uuid4().hex
        logger.error("unhandled exception", fields={"error": str(exc)}, event="error",
                     trace_id=trace)
        return JSONResponse(
            status_code=500,
            content=_body("INTERNAL_ERROR", "服务内部出错", {"trace_id": trace}, trace),
        )
