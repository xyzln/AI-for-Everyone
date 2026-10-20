"""Pydantic response/request models for the HTTP API (05-api-contract §2).

Domain models (HardwareReport / ModelInfo / RegistrySnapshot / BackendState) are
reused directly from their owning modules so the schema stays a single source of
truth. All models here are pydantic v2 so FastAPI can export a complete OpenAPI.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from ..backends import BackendState, RegistrySnapshot
from ..config import AifeConfig
from ..hardware import HardwareReport
from ..models.manager import ModelInfo


class Liveness(BaseModel):
    status: str = "ok"
    version: str
    uptime_s: float


class HealthCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""
    severity: str = "info"


class HealthReportResp(BaseModel):
    healthy: bool
    checks: dict[str, HealthCheck]
    version: str
    uptime_s: float


class SystemInfo(BaseModel):
    version: str
    platform: str
    python: str
    ollama_version: Optional[str] = None
    profile: str
    active_backend: str
    cpu_cores: Optional[int] = None
    system_ram_gb: Optional[float] = None


class ModelsResponse(BaseModel):
    models: list[ModelInfo] = Field(default_factory=list)


class CatalogEntry(BaseModel):
    name: str
    size_gb: float
    min_ram_gb: float
    tags: list[str] = Field(default_factory=list)
    recommended_for: str = ""
    recommended: bool = False


class ModelsAvailableResponse(BaseModel):
    models: list[CatalogEntry] = Field(default_factory=list)


class PullResponse(BaseModel):
    task_id: str


class DeleteResponse(BaseModel):
    deleted: bool
    name: str


class SetupStep(BaseModel):
    name: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[dict[str, Any]] = None


class SetupStatusResponse(BaseModel):
    run_id: Optional[str] = None
    status: str = "idle"
    steps: list[SetupStep] = Field(default_factory=list)
    current: Optional[str] = None

    @classmethod
    def empty(cls) -> "SetupStatusResponse":
        return cls(run_id=None, status="idle", steps=[], current=None)


class SetupRunResponse(BaseModel):
    run_id: str
    status: str


class SelectBackendResponse(BaseModel):
    active: str


class RestartResponse(BaseModel):
    restarted: bool


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage] = Field(default_factory=list)
    options: Optional[dict[str, Any]] = None
    stream: bool = True


class ChatResponse(BaseModel):
    message: ChatMessage
    usage: Optional[dict[str, Any]] = None
    done: bool = True


# ---- config views ---------------------------------------------------------- #
class ConfigView(BaseModel):
    config_version: int = 1
    hardware: dict[str, Any]
    ollama: dict[str, Any]
    models: dict[str, Any]
    backends: dict[str, Any]
    openai_compat: dict[str, Any]
    server: dict[str, Any]

    @classmethod
    def from_config(cls, cfg: AifeConfig) -> "ConfigView":
        def _mask_openai(d: dict) -> dict:
            d = dict(d)
            if d.get("api_key"):
                d["api_key"] = "***"
            return d

        return cls(
            config_version=cfg.config_version,
            hardware=cfg.hardware.model_dump(),
            ollama=cfg.ollama.model_dump(),
            models=cfg.models.model_dump(),
            backends=cfg.backends.model_dump(),
            openai_compat=_mask_openai(cfg.openai_compat.model_dump()),
            server=cfg.server.model_dump(),
        )


class ConfigPatch(BaseModel):
    hardware: Optional[dict[str, Any]] = None
    ollama: Optional[dict[str, Any]] = None
    models: Optional[dict[str, Any]] = None
    backends: Optional[dict[str, Any]] = None
    server: Optional[dict[str, Any]] = None


__all__ = [
    "Liveness", "HealthCheck", "HealthReportResp", "SystemInfo",
    "ModelsResponse", "CatalogEntry", "ModelsAvailableResponse",
    "PullResponse", "DeleteResponse", "SetupStep", "SetupStatusResponse",
    "SetupRunResponse", "SelectBackendResponse", "RestartResponse",
    "ChatMessage", "ChatRequest", "ChatResponse",
    "ConfigView", "ConfigPatch",
    "HardwareReport", "ModelInfo", "RegistrySnapshot", "BackendState",
]
