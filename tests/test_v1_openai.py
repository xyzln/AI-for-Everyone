"""OpenAI-compatible surface tests (D21/D22).

Uses the shared ``client`` fixture: active backend = ollama (mocked, returns
"Hello"). Asserts the OpenAI envelopes for /v1/models, /v1/chat/completions
(streaming + non-streaming) and that validation errors use the OpenAI error
envelope — not the /api unified body.
"""

import asyncio
import json

import httpx
import pytest


def _managed_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health" and request.method == "GET":
        return httpx.Response(200, json={"status": "ok"})
    if request.url.path == "/v1/models" and request.method == "GET":
        return httpx.Response(200, json={"data": [{"id": "qwen.gguf"}]})
    if request.url.path == "/v1/chat/completions" and request.method == "POST":
        body = json.loads(request.content)
        if body.get("stream"):
            sse = (
                'data: {"choices":[{"delta":{"content":"hi"}}]}\n'
                'data: {"choices":[{"delta":{}}],"usage":{"total_tokens":5}}\n'
                'data: [DONE]\n\n'
            )
            return httpx.Response(200, text=sse,
                                  headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json={
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": "hi"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        })
    return httpx.Response(404, json={"error": "not found"})


def _parse_sse_data(text: str) -> list:
    """Extract parsed JSON payloads from ``data:`` SSE frames."""
    out = []
    for frame in text.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                try:
                    out.append(json.loads(payload))
                except json.JSONDecodeError:
                    out.append(payload)  # [DONE]
    return out


def test_v1_models(client):
    r = client.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list) and body["data"]
    card = body["data"][0]
    assert card["object"] == "model" and card["owned_by"] == "aife"
    assert isinstance(card["created"], int)
    assert any(m["id"] == "qwen2.5:3b" for m in body["data"])


def test_v1_chat_non_streaming(client):
    r = client.post("/v1/chat/completions", json={
        "model": "qwen2.5:3b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["id"].startswith("chatcmpl-")
    assert isinstance(body["created"], int)
    assert body["model"] == "qwen2.5:3b"
    choice = body["choices"][0]
    assert choice["index"] == 0
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == "Hello"
    assert choice["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] >= 1


def test_v1_chat_streaming(client):
    r = client.post("/v1/chat/completions", json={
        "model": "qwen2.5:3b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    })
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    frames = _parse_sse_data(r.text)
    chunks = [f for f in frames if isinstance(f, dict)]
    assert chunks, "SSE 应至少包含一个 chunk"
    first = chunks[0]
    assert first["object"] == "chat.completion.chunk"
    assert first["choices"][0]["delta"]["content"] == "Hello"
    assert first["choices"][0]["finish_reason"] is None
    assert first["model"] == "qwen2.5:3b"
    assert "[DONE]" in frames
    assert frames[-1] == "[DONE]"


def test_v1_chat_validation_error_uses_openai_envelope(client):
    r = client.post("/v1/chat/completions", json={"messages": "not-a-list"})
    assert r.status_code == 400
    body = r.json()
    # OpenAI 信封：{"error": {"message", "type", ...}}，而非 /api 统一体
    assert "error" in body and isinstance(body["error"], dict)
    assert body["error"]["message"]
    assert body["error"]["type"] == "invalid_request_error"
    assert "code" not in body["error"] or body["error"]["code"]  # OpenAI code 可选


def test_v1_chat_empty_messages_rejected(client):
    r = client.post("/v1/chat/completions", json={"messages": [], "stream": False})
    assert r.status_code == 400
    assert r.json()["error"]["message"]


def test_v1_chat_model_optional(client):
    # model 缺省时应回退活跃后端默认模型（qwen2.5:3b）并正常返回
    r = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "qwen2.5:3b"
    assert body["choices"][0]["message"]["content"] == "Hello"


def test_api_errors_still_use_unified_envelope(client):
    # /api/* 不受 /v1 信封影响：仍是 {"error": {code, message, ...}}
    r = client.post("/api/chat", json={"messages": "not-a-list"})
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "VALIDATION"
    assert "details" in body["error"]


# ---- 端到端：活跃后端切到 llamacpp（adopted + MockTransport） ------------------ #
@pytest.fixture
def managed_client(monkeypatch):
    """Runtime with llamacpp active (adopted, mocked HTTP) — proves the full
    wiring: runtime registration -> registry -> /v1 route -> managed backend."""
    import aife.runtime as runtime_mod
    from aife.config import load_config
    from aife.runtime import Runtime

    cfg = load_config()
    cfg.llamacpp.enabled = True
    cfg.llamacpp.base_url = "http://127.0.0.1:18081"
    cfg.llamacpp.model = "qwen.gguf"
    cfg.backends.active = "llamacpp"
    cfg.backends.fallback = ["llamacpp"]
    rt = Runtime(cfg)

    async def _noop_startup():
        return None

    monkeypatch.setattr(rt.manager, "ensure_started", _noop_startup)
    be = rt.registry.get("llamacpp")
    assert be is not None and be._adopted()
    be._client = httpx.AsyncClient(
        transport=httpx.MockTransport(_managed_handler), base_url=be._base_url()
    )

    runtime_mod.reset_runtime()
    runtime_mod._runtime = rt
    from fastapi.testclient import TestClient

    from aife.server.app import app

    with TestClient(app) as c:
        yield c
    runtime_mod.reset_runtime()


def test_v1_models_managed_backend(managed_client):
    r = managed_client.get("/v1/models")
    assert r.status_code == 200
    assert [m["id"] for m in r.json()["data"]] == ["qwen.gguf"]


def test_v1_chat_non_streaming_managed_backend(managed_client):
    r = managed_client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "hi"}], "stream": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "qwen.gguf"
    assert body["choices"][0]["message"]["content"] == "hi"
    assert body["usage"]["total_tokens"] == 5


def test_v1_chat_streaming_managed_backend(managed_client):
    r = managed_client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "hi"}], "stream": True,
    })
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    frames = _parse_sse_data(r.text)
    chunks = [f for f in frames if isinstance(f, dict)]
    assert chunks[0]["choices"][0]["delta"]["content"] == "hi"
    assert chunks[-1]["choices"] == [] and chunks[-1]["usage"]["total_tokens"] == 5
    assert frames[-1] == "[DONE]"
