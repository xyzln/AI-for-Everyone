"""Managed OpenAI-compatible server backends (llama.cpp / vLLM) — base class.

Both ``llama-server`` and ``vllm serve`` expose the same OpenAI surface
(``GET /health``, ``GET /v1/models``, ``POST /v1/chat/completions`` with SSE
streaming), so the shared lifecycle lives here:

  - **adopted** mode: ``base_url`` set and no ``binary`` — connect to an
    already-running server; AIE never launches or kills it (same policy as the
    Ollama manager's adopted mode).
  - **managed** mode: ``binary`` set — AIE launches the subprocess, polls
    ``GET /health`` until ready (bounded by ``startup_timeout_s``), and
    terminates it on ``close()``.

Domain layer: httpx + stdlib only, no FastAPI (architecture §1.3 R1). SSE
parsing mirrors ``openai_compat.py`` (lines starting with ``data:``, ``[DONE]``
sentinel, normalized {delta, usage, done} contract from ``base.py``).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Any, AsyncIterator, Optional, Union

import httpx

from ..config import AifeConfig, LlamaCppConfig, VllmConfig
from ..ollama.protocol import OllamaProtocolError
from ..utils.logging import get_logger
from .base import BackendState, LLMBackend

logger = get_logger("aife.backends.managed_server")

SectionT = Union[LlamaCppConfig, VllmConfig]

# 单次健康探测的连接/读取超时（启动轮询与 health 用）
_PING_TIMEOUT = 5.0


class ManagedServerBackend(LLMBackend):
    """Base for local servers that speak the OpenAI protocol."""

    def __init__(self, cfg: AifeConfig, section: SectionT) -> None:
        super().__init__(cfg)
        self.section = section
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._client = httpx.AsyncClient(
            base_url=self._base_url(),
            # 流式读超时按 chat.stream_timeout_s（逐块计时，非整体）；
            # 连接超时按 network.connect_timeout_s，避免坏 host 长时间挂起。
            timeout=httpx.Timeout(
                cfg.chat.stream_timeout_s, connect=cfg.network.connect_timeout_s
            ),
        )

    # ---- to override -------------------------------------------------------- #
    def _launch_args(self) -> list[str]:
        """Command line for the managed subprocess (no shell)."""
        raise NotImplementedError

    # ---- helpers ------------------------------------------------------------ #
    def _base_url(self) -> str:
        if self.section.base_url:
            return self.section.base_url.rstrip("/")
        return f"http://{self.section.host}:{self.section.port}"

    def _adopted(self) -> bool:
        """External server: connect only, never launch/kill."""
        return bool(self.section.base_url) and not self.section.binary

    def _chat_url(self) -> str:
        return self._base_url() + "/v1/chat/completions"

    async def _ping_health(self) -> bool:
        try:
            r = await self._client.get(
                self._base_url() + "/health", timeout=_PING_TIMEOUT
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    # ---- lifecycle ---------------------------------------------------------- #
    async def ensure_started(self) -> None:
        """Adopt or launch the server; idempotent, raises OllamaProtocolError."""
        if not self.section.autostart:
            return
        if self._adopted() or not self.section.binary:
            return  # adopted / 无 binary：只连接，不拉起
        if await self._ping_health():
            return  # 已在运行（自拉起或外部已跑），直接复用
        if self._proc is not None and self._proc.returncode is None:
            await self._wait_ready()  # 上次已拉起但尚未就绪：继续等
            return
        await self._launch()
        await self._wait_ready()

    async def _launch(self) -> None:
        args = self._launch_args()
        logger.info("launching managed server",
                    fields={"backend": self.kind, "cmd": " ".join(args)})
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError as exc:
            raise OllamaProtocolError(
                f"找不到 {self.kind} 可执行文件: {args[0]}（{exc}）"
            ) from exc

    async def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.section.startup_timeout_s
        while True:
            if await self._ping_health():
                logger.info("managed server ready",
                            fields={"backend": self.kind, "pid": self._proc.pid if self._proc else None})
                return
            if self._proc is not None and self._proc.returncode is not None:
                raise OllamaProtocolError(
                    f"{self.kind} 进程提前退出（returncode={self._proc.returncode}）"
                )
            if time.monotonic() >= deadline:
                raise OllamaProtocolError(
                    f"{self.kind} 启动超时（{self.section.startup_timeout_s}s 内 /health 未就绪）"
                )
            await asyncio.sleep(1.0)

    async def close(self) -> None:
        # 只杀自己拉起的进程；adopted / 外部已在跑的服务永不终止。
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=10)
            except Exception:  # pragma: no cover - 兜底强杀
                try:
                    self._proc.kill()
                except Exception:
                    pass
            logger.info("managed server terminated", fields={"backend": self.kind})
        self._proc = None
        await self._client.aclose()

    # ---- health ------------------------------------------------------------- #
    async def health(self) -> BackendState:
        if self.section.autostart:
            try:
                await self.ensure_started()
            except OllamaProtocolError as exc:
                return self._state(False, f"启动失败: {exc}")
            except Exception as exc:  # pragma: no cover - defensive
                return self._state(False, f"启动异常: {exc}")
        base = self._base_url()
        try:
            r = await self._client.get(base + "/health", timeout=_PING_TIMEOUT)
            if r.status_code == 404:
                # 个别构建没有 /health：退回 /v1/models 判活
                r = await self._client.get(base + "/v1/models", timeout=_PING_TIMEOUT)
            if r.status_code == 200:
                mode = "adopted 外部服务" if self._adopted() else "managed"
                return self._state(True, f"{self.kind} 就绪（{base}，{mode}）")
            return self._state(False, f"{base}/health -> HTTP {r.status_code}")
        except httpx.HTTPError as exc:
            return self._state(False, f"无法连接 {base}: {exc}")

    # ---- chat --------------------------------------------------------------- #
    def _body(self, *, model: Optional[str], messages: list[dict[str, str]],
              options: Optional[dict[str, Any]], stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model or self.section.model,
            "messages": messages,
            "stream": stream,
        }
        if options:
            # 只透传 OpenAI 通用采样参数；其余（如 num_gpu）由 extra_args 承担。
            for key in ("temperature", "top_p", "max_tokens"):
                if options.get(key) is not None:
                    body[key] = options[key]
        return body

    async def chat(
        self,
        *,
        model: Optional[str],
        messages: list[dict[str, str]],
        options: Optional[dict[str, Any]] = None,
        stream: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        await self.ensure_started()
        body = self._body(model=model, messages=messages, options=options, stream=stream)
        try:
            if stream:
                async with self._client.stream("POST", self._chat_url(), json=body) as resp:
                    if resp.status_code != 200:
                        text = await resp.aread()
                        raise OllamaProtocolError(
                            f"{self.kind} chat -> {resp.status_code}: {text[:200]!r}"
                        )
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[len("data:"):].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        usage = data.get("usage")
                        if usage is not None:
                            yield {"usage": usage}
                        choices = data.get("choices") or []
                        content = (
                            choices[0].get("delta", {}).get("content")
                            if choices else None
                        )
                        if content:
                            yield {"delta": content}
                yield {"done": True}
            else:
                resp = await self._client.post(self._chat_url(), json=body)
                if resp.status_code != 200:
                    raise OllamaProtocolError(
                        f"{self.kind} chat -> {resp.status_code}: {resp.text[:200]!r}"
                    )
                data = resp.json()
                choices = data.get("choices") or []
                content = (
                    choices[0].get("message", {}).get("content", "")
                    if choices else ""
                )
                if content:
                    yield {"delta": content}
                if data.get("usage") is not None:
                    yield {"usage": data["usage"]}
                yield {"done": True}
        except httpx.HTTPError as exc:
            raise OllamaProtocolError(f"{self.kind} 请求失败: {exc}") from exc
