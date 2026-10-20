"""OpenAI-compatible remote backend (US5.4, optional fallback)."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx

from ..config import AifeConfig
from ..utils.logging import get_logger
from .base import BackendState, LLMBackend

logger = get_logger("aife.backends.openai_compat")


class OpenAICompatBackend(LLMBackend):
    name = "openai_compat"
    kind = "openai_compat"

    def __init__(self, cfg: AifeConfig) -> None:
        super().__init__(cfg)
        self.enabled = cfg.openai_compat.enabled
        self.base_url = cfg.openai_compat.base_url.rstrip("/")
        self.api_key = cfg.openai_compat.api_key
        self.model = cfg.openai_compat.model
        self._client = httpx.AsyncClient(
            timeout=cfg.openai_compat.timeout_s,
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> BackendState:
        if not self.enabled:
            return self._state(False, "openai_compat 未启用")
        if not self.api_key:
            return self._state(False, "缺少 api_key（需通过 ${AIE_OPENAI_API_KEY} 注入）")
        try:
            r = await self._client.get(self.base_url, timeout=5.0)
            reachable = r.status_code < 500
            return self._state(reachable, f"远端 {self.base_url} 可达（HTTP {r.status_code}）"
                               if reachable else f"远端返回 {r.status_code}")
        except httpx.HTTPError as exc:
            return self._state(False, f"无法连接远端: {exc}")

    async def chat(
        self,
        *,
        model: Optional[str],
        messages: list[dict[str, str]],
        options: Optional[dict[str, Any]] = None,
        stream: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        model = model or self.model
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if options:
            if "temperature" in options:
                body["temperature"] = options["temperature"]
            if "top_p" in options:
                body["top_p"] = options["top_p"]
            if "max_tokens" in options:
                body["max_tokens"] = options["max_tokens"]
        try:
            async with self._client.stream("POST", self.base_url + "/chat/completions",
                                           json=body) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    raise RuntimeError(f"openai_compat -> {resp.status_code}: {text[:200]!r}")
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        yield {"done": True}
                        return
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    usage = data.get("usage")
                    if usage is not None:
                        yield {"usage": usage}
                    choices = data.get("choices") or []
                    if choices and choices[0].get("delta", {}).get("content"):
                        yield {"delta": choices[0]["delta"]["content"]}
                yield {"done": True}
        except httpx.HTTPError as exc:
            raise RuntimeError(f"openai_compat 请求失败: {exc}") from exc
