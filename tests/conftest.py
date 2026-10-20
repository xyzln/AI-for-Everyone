"""Shared pytest fixtures (08-test-acceptance §mock strategy).

Tests run without GPU / Ollama / network: the Ollama HTTP client is replaced with
an httpx MockTransport returning canned NDJSON, and the manager is patched to
report healthy + installed. The runtime is injected as the process-wide singleton
so the FastAPI app uses the mock.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

import aife.runtime as runtime_mod
from aife.config import load_config
from aife.runtime import Runtime


def _make_ollama_handler() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if path == "/api/version" and method == "GET":
            return httpx.Response(200, json={"version": "0.5.7"})
        if path == "/api/tags" and method == "GET":
            return httpx.Response(200, json={"models": [
                {"name": "qwen2.5:3b", "size": 2_000_000_000,
                 "details": {"family": "qwen2", "parameter_size": "3B",
                             "quantization_level": "Q4_K_M"},
                 "modified_at": "2025-01-01T00:00:00Z"},
            ]})
        if path == "/api/ps" and method == "GET":
            return httpx.Response(200, json={"models": []})
        if path == "/api/chat" and method == "POST":
            body = (
                '{"model":"qwen2.5:3b","message":{"role":"assistant","content":"Hello"},"done":false}\n'
                '{"model":"qwen2.5:3b","done":true,"usage":{"prompt_tokens":3,"completion_tokens":1}}\n'
            )
            return httpx.Response(200, text=body)
        if path == "/api/pull" and method == "POST":
            return httpx.Response(200, text='{"status":"success","completed":1,"total":1}\n')
        if path == "/api/delete" and method == "DELETE":
            return httpx.Response(200, json={"status": "success"})
        if path == "/api/show" and method == "POST":
            return httpx.Response(200, json={"details": {"family": "qwen2"}})
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


@pytest.fixture
def runtime(monkeypatch):
    """A runtime with a mocked, healthy Ollama and a default installed model."""
    cfg = load_config()
    cfg.models.default = "qwen2.5:3b"  # ensure default model present in mock tags
    rt = Runtime(cfg)

    rt.manager.state.status = "running"
    rt.manager.state.version = "0.5.7"
    rt.manager.state.adopted = True

    async def _healthy():
        return True

    monkeypatch.setattr(rt.manager, "is_healthy", _healthy)
    monkeypatch.setattr(rt.manager, "is_installed", lambda: True)
    monkeypatch.setattr(rt.manager, "binary_version", lambda: "0.5.7")
    monkeypatch.setattr(rt.manager, "ensure_started", lambda: asyncio.sleep(0, result="running"))

    transport = _make_ollama_handler()
    rt.manager.client._client = httpx.AsyncClient(
        transport=transport, base_url=rt.manager.client.base_url
    )

    runtime_mod.reset_runtime()
    runtime_mod._runtime = rt
    yield rt
    runtime_mod.reset_runtime()


@pytest.fixture
def client(runtime):
    from fastapi.testclient import TestClient
    from aife.server.app import app

    with TestClient(app) as c:
        yield c
