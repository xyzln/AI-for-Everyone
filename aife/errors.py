"""Unified error contract (05-api-contract §3).

Pure module — depends only on pydantic + stdlib so the domain layer can raise
``AIEError`` without importing FastAPI. ``aife.server.errors`` registers the
FastAPI handlers that turn these into the unified response body.

All errors return ``{"error": {"code", "message", "details", "trace_id"}}``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class ErrorCode(str, Enum):
    # 400
    VALIDATION = "VALIDATION"
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFIG_READONLY = "CONFIG_READONLY"
    STEP_INVALID = "STEP_INVALID"
    MODEL_INVALID_NAME = "MODEL_INVALID_NAME"
    BACKEND_UNKNOWN = "BACKEND_UNKNOWN"
    # 404
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    SETUP_NOT_FOUND = "SETUP_NOT_FOUND"
    ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"
    # 405
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    # 409
    PULL_IN_PROGRESS = "PULL_IN_PROGRESS"
    SETUP_RUNNING = "SETUP_RUNNING"
    CONFIG_RESTART_REQUIRED = "CONFIG_RESTART_REQUIRED"
    OLLAMA_NOT_MANAGED = "OLLAMA_NOT_MANAGED"
    # 429 (reserved)
    RATE_LIMITED = "RATE_LIMITED"
    # 500
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CONFIG_RELOAD_FAILED = "CONFIG_RELOAD_FAILED"
    CONFIG_VERSION_UNSUPPORTED = "CONFIG_VERSION_UNSUPPORTED"
    # 503
    OLLAMA_UNAVAILABLE = "OLLAMA_UNAVAILABLE"
    BACKEND_UNHEALTHY = "BACKEND_UNHEALTHY"
    MODEL_NOT_LOADED = "MODEL_NOT_LOADED"
    # 504
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"


# code -> HTTP status (05-api-contract §3 status table)
HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION: 400,
    ErrorCode.CONFIG_INVALID: 400,
    ErrorCode.CONFIG_READONLY: 400,
    ErrorCode.STEP_INVALID: 400,
    ErrorCode.MODEL_INVALID_NAME: 400,
    ErrorCode.BACKEND_UNKNOWN: 400,
    ErrorCode.MODEL_NOT_FOUND: 404,
    ErrorCode.SETUP_NOT_FOUND: 404,
    ErrorCode.ROUTE_NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.PULL_IN_PROGRESS: 409,
    ErrorCode.SETUP_RUNNING: 409,
    ErrorCode.CONFIG_RESTART_REQUIRED: 409,
    ErrorCode.OLLAMA_NOT_MANAGED: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.CONFIG_RELOAD_FAILED: 500,
    ErrorCode.CONFIG_VERSION_UNSUPPORTED: 500,
    ErrorCode.OLLAMA_UNAVAILABLE: 503,
    ErrorCode.BACKEND_UNHEALTHY: 503,
    ErrorCode.MODEL_NOT_LOADED: 503,
    ErrorCode.UPSTREAM_TIMEOUT: 504,
}


def http_status_for(code: ErrorCode) -> int:
    return HTTP_STATUS.get(code, 400)


class ErrorBody(BaseModel):
    """Core error body — reused by HTTP, WS and SSE channels (05 §2.18)."""

    code: str
    message: str
    details: Optional[dict[str, Any]] = None
    trace_id: str = ""


class ErrorResponse(BaseModel):
    """HTTP error envelope (always ``{"error": {...}}``)."""

    error: ErrorBody


class AIEError(Exception):
    """Domain exception carrying a stable DOMAIN_REASON code.

    Raise this from anywhere (domain / routes); ``aife.server.errors`` maps it
    to the unified response body. Never raise ``fastapi.HTTPException`` directly
    in route bodies (05 §3 processing chain).
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details
        self.trace_id = trace_id or ""
        self.status_code = status_code or http_status_for(code)
        super().__init__(message)

    def to_body(self) -> ErrorBody:
        return ErrorBody(
            code=self.code.value,
            message=self.message,
            details=self.details,
            trace_id=self.trace_id,
        )

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(error=self.to_body())
