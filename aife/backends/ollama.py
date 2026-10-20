"""Ollama-backed inference (managed subprocess)."""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

from ..config import AifeConfig
from ..hardware import ResolvedProfile
from ..models.catalog import catalog_model_for_tier
from ..ollama.manager import OllamaManager
from ..ollama.protocol import OllamaProtocolError
from ..utils.logging import get_logger
from .base import BackendState, LLMBackend

logger = get_logger("aife.backends.ollama")


class OllamaBackend(LLMBackend):
    name = "ollama"
    kind = "ollama"

    def __init__(self, cfg: AifeConfig, manager: OllamaManager, resolved: ResolvedProfile) -> None:
        super().__init__(cfg)
        self.manager = manager
        self.resolved = resolved

    def default_model(self) -> Optional[str]:
        if self.cfg.models.default:
            return self.cfg.models.default
        tier = self.resolved.catalog_tier
        return catalog_model_for_tier(tier) if tier else None

    async def health(self) -> BackendState:
        try:
            if not await self.manager.is_healthy():
                return self._state(False, "Ollama 不可达")
            tags = await self.manager.client.tags()
            names = [m.get("name") for m in tags]
            model = self.default_model()
            if model and model not in names:
                return self._state(
                    False, f"缺少默认模型 {model}",
                    last_error={"code": "MODEL_NOT_LOADED", "model": model},
                )
            return self._state(
                True,
                f"Ollama {self.manager.state.version or ''} 就绪"
                + (f"，默认模型 {model}" if model else "（无默认模型）"),
            )
        except OllamaProtocolError as exc:
            return self._state(False, str(exc))
        except Exception as exc:  # pragma: no cover
            return self._state(False, f"健康检查异常: {exc}")

    async def chat(
        self,
        *,
        model: Optional[str],
        messages: list[dict[str, str]],
        options: Optional[dict[str, Any]] = None,
        stream: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        model = model or self.default_model()
        if not model:
            raise RuntimeError("no model available for ollama backend")
        opts: dict[str, Any] = {}
        # request-level num_gpu from the resolved profile (NOT an env var).
        ng = self.resolved.request_options.get("num_gpu")
        if ng is not None:
            opts["num_gpu"] = ng
        if options:
            opts.update(options)
        async for obj in self.manager.client.chat(
            model=model, messages=messages, options=opts or None, stream=stream,
            keep_alive=self.cfg.ollama.keep_alive,
        ):
            if obj.get("message") and obj["message"].get("content"):
                yield {"delta": obj["message"]["content"]}
            if obj.get("done"):
                if obj.get("usage") is not None:
                    yield {"usage": obj["usage"]}
                yield {"done": True}
