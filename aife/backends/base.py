"""Backend abstraction: a uniform interface over inference providers.

A ``LLMBackend`` exposes ``health()`` and streaming ``chat()``. ``ollama`` and
``openai_compat`` are the two implementations. Backends never import the server
(architecture §1.3 R3). Health for Ollama requires the default model to be
installed — missing model == unhealthy (Octop M14 lesson, 02-architecture §5.2).

Streaming contract: ``chat()`` is an async generator that yields normalized dicts:
  - ``{"delta": "<text>"}``                one content chunk
  - ``{"usage": {...}}``                   optional usage block
  - ``{"done": True}``                     end of stream
The chat route maps these to SSE events.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel, Field

from ..config import AifeConfig
from ..utils.logging import get_logger

logger = get_logger("aife.backends.base")


class BackendState(BaseModel):
    name: str
    kind: str
    healthy: bool = False
    detail: str = ""
    last_error: Optional[dict[str, Any]] = None
    last_checked_at: Optional[datetime] = None


class BackendSwitch(BaseModel):
    frm: str
    to: str
    reason: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LLMBackend(ABC):
    name: str = "base"
    kind: str = "base"

    def __init__(self, cfg: AifeConfig) -> None:
        self.cfg = cfg

    @abstractmethod
    async def health(self) -> BackendState: ...

    @abstractmethod
    async def chat(
        self,
        *,
        model: Optional[str],
        messages: list[dict[str, str]],
        options: Optional[dict[str, Any]] = None,
        stream: bool = True,
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def close(self) -> None:  # pragma: no cover - default noop
        pass

    def _state(self, healthy: bool, detail: str = "",
               last_error: Optional[dict] = None) -> BackendState:
        return BackendState(
            name=self.name, kind=self.kind, healthy=healthy, detail=detail,
            last_error=last_error, last_checked_at=datetime.now(timezone.utc),
        )
