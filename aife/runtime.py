"""Runtime singleton — the single composition root (architecture §1.3 R3).

Assembles config → hardware profile → Ollama manager → model manager → backend
registry, and owns the event bus used to fan out WS/SSE events. Importing this
module brings in server only transitively (the event bus is defined here so the
domain layer never imports FastAPI).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .config import AifeConfig, load_config
from .hardware import ResolvedProfile, build_report, resolve_profile
from .models.manager import ModelManager
from .ollama.manager import OllamaManager
from .backends import BackendRegistry
from .backends.llamacpp import LlamaCppBackend
from .backends.ollama import OllamaBackend
from .backends.openai_compat import OpenAICompatBackend
from .backends.vllm import VllmBackend
from .utils.logging import get_logger

logger = get_logger("aife.runtime")


class EventBus:
    """In-process pub/sub. WS/SSE adapters subscribe; domain code publishes."""

    def __init__(self) -> None:
        self._subs: set[Callable[[dict[str, Any]], None]] = set()

    def subscribe(self, cb: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self._subs.add(cb)
        return lambda: self._subs.discard(cb)

    def publish(self, etype: str, payload: dict[str, Any]) -> dict[str, Any]:
        ev = {
            "type": etype,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") +
                 f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
            "payload": payload,
        }
        for cb in list(self._subs):
            try:
                cb(ev)
            except Exception:  # pragma: no cover
                pass
        return ev


def _resolve_proxy(cfg: AifeConfig) -> Optional[str]:
    if cfg.network.proxy:
        return cfg.network.proxy
    return os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or None


class Runtime:
    def __init__(self, cfg: Optional[AifeConfig] = None) -> None:
        self.cfg = cfg or load_config()
        self.resolved: ResolvedProfile = resolve_profile(
            explicit_device=self.cfg.hardware.device
        )
        self.report = build_report(self.resolved)
        self.bus = EventBus()
        self.manager = OllamaManager(
            self.cfg.ollama, self.resolved, proxy=_resolve_proxy(self.cfg)
        )
        self.model_manager = ModelManager(
            self.cfg, self.manager.client, publish=self.bus.publish
        )
        self.registry = BackendRegistry(self.cfg)
        self.registry.register(OllamaBackend(self.cfg, self.manager, self.resolved))
        if self.cfg.openai_compat.enabled:
            self.registry.register(OpenAICompatBackend(self.cfg))
        if self.cfg.llamacpp.enabled:
            self.registry.register(LlamaCppBackend(self.cfg, self.cfg.llamacpp))
        if self.cfg.vllm.enabled:
            self.registry.register(VllmBackend(self.cfg, self.cfg.vllm))
        self._started = False

    async def startup(self) -> None:
        try:
            await self.manager.ensure_started()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("ollama startup failed", fields={"error": str(exc)})
        self._started = True

    async def shutdown(self) -> None:
        try:
            await self.manager.aclose()
        except Exception:  # pragma: no cover
            pass
        for backend in self.registry._backends.values():
            try:
                await backend.close()
            except Exception:  # pragma: no cover
                pass
        self._started = False

    def publish(self, etype: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.bus.publish(etype, payload)


_runtime: Optional[Runtime] = None


def get_runtime(cfg: Optional[AifeConfig] = None) -> Runtime:
    """Return the process-wide runtime, building it on first call."""
    global _runtime
    if _runtime is None or cfg is not None:
        _runtime = Runtime(cfg)
    return _runtime


def reset_runtime() -> None:
    global _runtime
    _runtime = None
