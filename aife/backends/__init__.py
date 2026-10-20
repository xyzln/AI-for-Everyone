"""Backend registry: registration, active selection, fallback chain, health."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from ..config import AifeConfig
from ..utils.logging import get_logger
from .base import BackendState, BackendSwitch, LLMBackend
from .llamacpp import LlamaCppBackend
from .managed_server import ManagedServerBackend
from .ollama import OllamaBackend
from .openai_compat import OpenAICompatBackend
from .vllm import VllmBackend

logger = get_logger("aife.backends")


class RegistrySnapshot(BaseModel):
    active: str
    chain: list[str] = Field(default_factory=list)
    backends: dict[str, BackendState] = Field(default_factory=dict)
    last_switch: Optional[BackendSwitch] = None


class BackendRegistry:
    def __init__(self, cfg: AifeConfig) -> None:
        self.cfg = cfg
        self._backends: dict[str, LLMBackend] = {}
        self.active = cfg.backends.active
        self.fallback = list(cfg.backends.fallback)
        self.last_switch: Optional[BackendSwitch] = None
        self.last_errors: dict[str, dict] = {}
        self._states: dict[str, BackendState] = {}

    def register(self, backend: LLMBackend) -> None:
        self._backends[backend.name] = backend

    def get(self, name: str) -> Optional[LLMBackend]:
        return self._backends.get(name)

    def current(self) -> Optional[LLMBackend]:
        return self._backends.get(self.active)

    def switch_to(self, name: str, reason: str) -> BackendSwitch:
        if name not in self._backends:
            raise KeyError(name)
        old = self.active
        self.active = name
        self.last_switch = BackendSwitch(frm=old, to=name, reason=reason)
        logger.info("backend switched", fields={"from": old, "to": name, "reason": reason})
        return self.last_switch

    async def health_all(self) -> dict[str, BackendState]:
        for name, backend in self._backends.items():
            try:
                state = await backend.health()
            except Exception as exc:  # pragma: no cover
                state = backend._state(False, f"健康检查异常: {exc}")
            if not state.healthy and state.last_error:
                self.last_errors[name] = state.last_error
            self._states[name] = state
        return dict(self._states)

    async def snapshot(self) -> RegistrySnapshot:
        states = await self.health_all()
        return RegistrySnapshot(
            active=self.active,
            chain=list(self.fallback),
            backends={k: v for k, v in states.items()},
            last_switch=self.last_switch,
        )


__all__ = [
    "BackendRegistry",
    "RegistrySnapshot",
    "BackendState",
    "BackendSwitch",
    "LLMBackend",
    "ManagedServerBackend",
    "OllamaBackend",
    "OpenAICompatBackend",
    "LlamaCppBackend",
    "VllmBackend",
]
