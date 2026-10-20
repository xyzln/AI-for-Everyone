"""Model manager: list / pull (task-state, dedup, progress) / delete / verify.

Pulls run as background asyncio tasks and publish WS events via the injected
``publish(type, payload)`` callback (runtime wires this to the event bus, so the
domain layer never imports the server — architecture §1.3 R4).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from ..config import AifeConfig
from ..errors import AIEError, ErrorCode
from ..ollama.protocol import OllamaClient, OllamaProtocolError
from ..utils.logging import get_logger

logger = get_logger("aife.models.manager")

PublishFn = Callable[[str, dict[str, Any]], None]


class ModelInfo(BaseModel):
    name: str
    size: int = 0
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""
    modified_at: Optional[str] = None


class ModelManager:
    def __init__(
        self,
        cfg: AifeConfig,
        client: OllamaClient,
        publish: Optional[PublishFn] = None,
    ) -> None:
        self.cfg = cfg
        self.client = client
        self.publish = publish
        self._tasks: dict[str, asyncio.Task] = {}

    # ---- listing ----------------------------------------------------------- #
    async def list_installed(self) -> list[ModelInfo]:
        try:
            raw = await self.client.tags()
        except OllamaProtocolError as exc:
            raise AIEError(ErrorCode.OLLAMA_UNAVAILABLE, str(exc))
        return [self._to_info(m) for m in raw]

    def _to_info(self, raw: dict[str, Any]) -> ModelInfo:
        details = raw.get("details") or {}
        return ModelInfo(
            name=raw.get("name", ""),
            size=int(raw.get("size", 0) or 0),
            family=details.get("family", ""),
            parameter_size=str(details.get("parameter_size", "")),
            quantization=details.get("quantization_level", ""),
            modified_at=raw.get("modified_at"),
        )

    async def show(self, model: str) -> dict[str, Any]:
        try:
            return await self.client.show(model)
        except OllamaProtocolError as exc:
            raise AIEError(ErrorCode.MODEL_NOT_FOUND, str(exc), details={"model": model})

    # ---- pulling ----------------------------------------------------------- #
    def pull(self, model: str) -> str:
        """Start (or dedupe) a pull. Returns a task id. Raises on conflict."""
        if not self._valid_name(model):
            raise AIEError(
                ErrorCode.MODEL_INVALID_NAME, f"非法模型名: {model}",
                details={"name": model},
            )
        existing = self._tasks.get(model)
        if existing is not None and not existing.done():
            raise AIEError(
                ErrorCode.PULL_IN_PROGRESS, "已有拉取任务在进行中",
                details={"task_id": getattr(existing, "task_id", model), "model": model},
            )
        task_id = f"pull-{model}"
        task = asyncio.create_task(self._run_pull(model, task_id))
        task.task_id = task_id  # type: ignore[attr-defined]
        self._tasks[model] = task
        return task_id

    async def _run_pull(self, model: str, task_id: str) -> None:
        try:
            def _progress(status: str, completed: int, total: Optional[int]) -> None:
                if self.publish:
                    self.publish("model.pull_progress", {
                        "task_id": task_id, "model": model, "status": status,
                        "completed": completed, "total": total,
                    })

            await self.client.pull(model, progress=_progress)
            if self.publish:
                self.publish("model.pull_done", {"task_id": task_id, "model": model})
            logger.info("pull complete", fields={"model": model})
        except OllamaProtocolError as exc:
            logger.error("pull failed", fields={"model": model, "error": str(exc)})
            if self.publish:
                self.publish("error", {
                    "code": ErrorCode.OLLAMA_UNAVAILABLE.value,
                    "message": f"拉取 {model} 失败: {exc}",
                })
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            logger.error("pull error", fields={"model": model, "error": str(exc)})
        finally:
            self._tasks.pop(model, None)

    # ---- deletion ---------------------------------------------------------- #
    async def delete(self, model: str) -> None:
        try:
            await self.client.delete(model)
        except OllamaProtocolError as exc:
            # 404 => not installed
            if "404" in str(exc):
                raise AIEError(ErrorCode.MODEL_NOT_FOUND, f"模型未安装: {model}",
                               details={"model": model})
            raise AIEError(ErrorCode.OLLAMA_UNAVAILABLE, str(exc))

    @staticmethod
    def _valid_name(model: str) -> bool:
        import re

        return bool(re.match(r"^[a-z0-9._:/-]+$", model))
