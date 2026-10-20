"""Backend contract tests (08-test-acceptance §backend).

Proves the OllamaBackend: (1) injects request-level ``num_gpu`` from the resolved
profile (NOT an env var — verified errata), (2) normalizes Ollama NDJSON chunks to
the streaming contract {delta, usage, done}, (3) reports unhealthy when the default
model is not installed (Octop M14 lesson).
"""

import asyncio

from aife.config import load_config
from aife.hardware import resolve_profile
from aife.backends.ollama import OllamaBackend


class FakeOllamaClient:
    def __init__(self):
        self.last_kwargs = None

    async def chat(self, *, model, messages, options=None, stream=True, keep_alive=None):
        self.last_kwargs = dict(
            model=model, messages=messages, options=options, stream=stream, keep_alive=keep_alive
        )
        yield {"message": {"content": "hi"}, "done": False}
        yield {"done": True, "usage": {"total_tokens": 5}}

    async def tags(self):
        return [{"name": "qwen2.5:3b"}]


class FakeManager:
    def __init__(self, client):
        self.client = client
        self.state = type("S", (), {"version": "0.5.7"})()

    async def is_healthy(self):
        return True


def _backend(request_options, default_model="qwen2.5:3b"):
    cfg = load_config()
    cfg.models.default = default_model
    resolved = resolve_profile(explicit_device=cfg.hardware.device)
    resolved.request_options = dict(request_options)
    client = FakeOllamaClient()
    mgr = FakeManager(client)
    be = OllamaBackend(cfg, mgr, resolved)
    return be, client


def test_num_gpu_injected_from_profile():
    be, client = _backend({"num_gpu": 42})
    out = []

    async def run():
        async for ev in be.chat(model="qwen2.5:3b", messages=[{"role": "user", "content": "x"}]):
            out.append(ev)

    asyncio.run(run())
    assert client.last_kwargs["options"]["num_gpu"] == 42
    # normalization contract
    assert out[0] == {"delta": "hi"}
    assert any(ev.get("done") for ev in out)
    assert any("usage" in ev for ev in out)


def test_no_num_gpu_when_absent():
    be, client = _backend({})

    async def run():
        async for _ in be.chat(model="qwen2.5:3b", messages=[]):
            pass

    asyncio.run(run())
    assert "num_gpu" not in (client.last_kwargs["options"] or {})


def test_health_unhealthy_without_default_model():
    be, _ = _backend({}, default_model="nonexistent:latest")

    async def run():
        return await be.health()

    st = asyncio.run(run())
    assert st.healthy is False
    assert st.last_error and st.last_error.get("code") == "MODEL_NOT_LOADED"
