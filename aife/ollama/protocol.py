"""Ollama HTTP protocol client (NDJSON / SSE) — pure httpx, no GPU.

Implements the verified Ollama surface used by AIE: /api/version, /api/tags,
/api/ps, /api/chat, /api/generate, /api/pull, /api/show, /api/delete
(02-architecture §5.2 / 04-data-model §2.3). All network calls go through a single
AsyncClient so tests can substitute a MockTransport (08-test-acceptance §mock).
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable, Optional

import httpx

from ..utils.logging import get_logger

logger = get_logger("aife.ollama.protocol")

DEFAULT_TIMEOUT = 600.0
# Progress callback receives (status:str, completed:int, total:Optional[int]).
PullProgress = Callable[[str, int, Optional[int]], None]


class OllamaProtocolError(Exception):
    """Raised when Ollama returns an error object or is unreachable."""


class OllamaClient:
    def __init__(self, base_url: str, *, timeout: float = DEFAULT_TIMEOUT,
                 proxy: Optional[str] = None, client: Optional[httpx.AsyncClient] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._owned = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, proxy=proxy,
            headers={"Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        if self._owned:
            await self._client.aclose()

    def _url(self, path: str) -> str:
        # 始终使用绝对 URL，使注入的 MockTransport 客户端无需预设 base_url。
        return self.base_url + path

    async def _get_json(self, path: str) -> Any:
        try:
            resp = await self._client.get(self._url(path))
        except httpx.HTTPError as exc:
            raise OllamaProtocolError(f"Ollama 请求失败: {exc}") from exc
        if resp.status_code != 200:
            raise OllamaProtocolError(f"Ollama {path} -> {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def version(self) -> str:
        data = await self._get_json("/api/version")
        return data.get("version", "")

    async def tags(self) -> list[dict[str, Any]]:
        data = await self._get_json("/api/tags")
        return data.get("models", []) or []

    async def ps(self) -> list[dict[str, Any]]:
        try:
            data = await self._get_json("/api/ps")
            return data.get("models", []) or []
        except OllamaProtocolError:
            return []  # /api/ps missing on older versions — degrade (D11)

    async def show(self, model: str) -> dict[str, Any]:
        try:
            resp = await self._client.post(self._url("/api/show"), json={"name": model, "verbose": False})
        except httpx.HTTPError as exc:
            raise OllamaProtocolError(f"Ollama 请求失败: {exc}") from exc
        if resp.status_code != 200:
            raise OllamaProtocolError(f"show {model} -> {resp.status_code}")
        return resp.json()

    async def delete(self, model: str) -> None:
        try:
            resp = await self._client.request(
                "DELETE",
                self._url("/api/delete"),
                content=json.dumps({"name": model}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise OllamaProtocolError(f"Ollama 请求失败: {exc}") from exc
        if resp.status_code not in (200, 404):
            raise OllamaProtocolError(f"delete {model} -> {resp.status_code}")

    # ---- streaming endpoints ------------------------------------------------ #
    async def _stream_lines(self, method: str, path: str, json_body: dict[str, Any],
                            ) -> AsyncIterator[dict[str, Any]]:
        try:
            async with self._client.stream(method, self._url(path), json=json_body) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise OllamaProtocolError(f"{path} -> {resp.status_code}: {body[:200]!r}")
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("non-json ndjson line", fields={"line": line[:200]})
        except httpx.HTTPError as exc:
            raise OllamaProtocolError(f"Ollama 流请求失败: {exc}") from exc

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: Optional[dict[str, Any]] = None,
        stream: bool = True,
        keep_alive: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if options:
            body["options"] = options
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        async for obj in self._stream_lines("POST", "/api/chat", body):
            yield obj

    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        options: Optional[dict[str, Any]] = None,
        stream: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        body: dict[str, Any] = {"model": model, "prompt": prompt, "stream": stream}
        if options:
            body["options"] = options
        async for obj in self._stream_lines("POST", "/api/generate", body):
            yield obj

    async def pull(
        self,
        model: str,
        *,
        progress: Optional[PullProgress] = None,
        insecure: bool = False,
    ) -> None:
        body = {"name": model, "stream": True, "insecure": insecure}
        last_total: Optional[int] = None
        async for obj in self._stream_lines("POST", "/api/pull", body):
            status = obj.get("status", "")
            completed = int(obj.get("completed", 0) or 0)
            total = obj.get("total")
            if total:
                last_total = int(total)
            if progress:
                progress(status, completed, last_total)
            if obj.get("status") == "success" or obj.get("done"):
                return
