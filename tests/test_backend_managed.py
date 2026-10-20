"""Managed-server backend tests (llama.cpp / vLLM shared base).

No GPU / no real subprocess: an ``httpx.MockTransport`` fakes the OpenAI surface
(``GET /health`` + ``POST /v1/chat/completions`` SSE), and launch paths are
asserted via ``_launch_args()`` without executing anything.
"""

import asyncio
import json

import httpx
import pytest

from aife.backends.llamacpp import LlamaCppBackend
from aife.backends.managed_server import ManagedServerBackend
from aife.backends.vllm import VllmBackend
from aife.config import AifeConfig, LlamaCppConfig, VllmConfig

SSE_BODY = (
    'data: {"choices":[{"delta":{"content":"hi"}}]}\n'
    'data: {"choices":[{"delta":{}}],"usage":{"total_tokens":5}}\n'
    'data: [DONE]\n\n'
)


class _Recorder:
    """Captures requests the backend makes through the mock transport."""

    def __init__(self):
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/health" and request.method == "GET":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/chat/completions" and request.method == "POST":
            body = json.loads(request.content)
            if body.get("stream"):
                return httpx.Response(200, text=SSE_BODY,
                                      headers={"Content-Type": "text/event-stream"})
            return httpx.Response(200, json={
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            })
        return httpx.Response(404, json={"error": "not found"})


def _backend(cls, section: object, recorder: _Recorder | None = None) -> ManagedServerBackend:
    cfg = AifeConfig()
    be = cls(cfg, section)
    transport = httpx.MockTransport((recorder or _Recorder()).handler)
    be._client = httpx.AsyncClient(transport=transport, base_url=be._base_url())
    return be


def _collect(be, **kwargs):
    out = []

    async def run():
        async for ev in be.chat(**kwargs):
            out.append(ev)

    asyncio.run(run())
    return out


# ---- chat normalization ----------------------------------------------------- #
def test_chat_stream_normalizes_sse():
    be = _backend(LlamaCppBackend, LlamaCppConfig(model="m.gguf", binary="llama-server"))
    out = _collect(be, model=None, messages=[{"role": "user", "content": "x"}], stream=True)
    assert out[0] == {"delta": "hi"}
    assert {"usage": {"total_tokens": 5}} in out
    assert out[-1] == {"done": True}


def test_chat_non_stream_normalizes_json():
    be = _backend(LlamaCppBackend, LlamaCppConfig(model="m.gguf", binary="llama-server"))
    out = _collect(be, model="m.gguf", messages=[{"role": "user", "content": "x"}], stream=False)
    assert {"delta": "hi"} in out
    assert out[-1] == {"done": True}
    assert any("usage" in ev for ev in out)


def test_chat_options_mapped_to_openai_params():
    rec = _Recorder()
    be = _backend(LlamaCppBackend, LlamaCppConfig(model="m.gguf", binary="llama-server"), rec)
    _collect(be, model=None, messages=[{"role": "user", "content": "x"}], stream=False,
             options={"temperature": 0.5, "top_p": 0.9, "max_tokens": 8, "num_gpu": 99})
    sent = json.loads(rec.requests[-1].content)
    assert sent["model"] == "m.gguf"  # model 缺省时回退 section.model
    assert sent["temperature"] == 0.5 and sent["top_p"] == 0.9 and sent["max_tokens"] == 8
    assert "num_gpu" not in sent  # 非 OpenAI 通用参数不透传


# ---- launch args ------------------------------------------------------------ #
def test_llamacpp_launch_args():
    section = LlamaCppConfig(
        binary="llama-server", model="qwen.gguf", host="127.0.0.1", port=8081,
        extra_args=["-ngl", "99", "-c", "8192"],
    )
    be = _backend(LlamaCppBackend, section)
    assert be._launch_args() == [
        "llama-server", "-m", "qwen.gguf",
        "--host", "127.0.0.1", "--port", "8081",
        "-ngl", "99", "-c", "8192",
    ]
    assert be.name == "llamacpp" and be.kind == "llamacpp"


def test_vllm_launch_args_python_module():
    section = VllmConfig(binary="python", model="Qwen/Qwen2.5-7B", host="0.0.0.0", port=8000)
    be = _backend(VllmBackend, section)
    assert be._launch_args() == [
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", "Qwen/Qwen2.5-7B", "--host", "0.0.0.0", "--port", "8000",
    ]
    assert be.name == "vllm" and be.kind == "vllm"


def test_vllm_launch_args_console_script():
    section = VllmConfig(binary="vllm", model="Qwen/Qwen2.5-7B", extra_args=["--dtype", "half"])
    be = _backend(VllmBackend, section)
    assert be._launch_args() == [
        "vllm", "serve", "Qwen/Qwen2.5-7B",
        "--host", "127.0.0.1", "--port", "8000", "--dtype", "half",
    ]


def test_vllm_launch_args_binary_default_and_interpreter_path():
    be = _backend(VllmBackend, VllmConfig(model="m"))
    assert be._launch_args()[0] == "vllm"  # binary 缺省回退 vllm
    be2 = _backend(VllmBackend, VllmConfig(binary="/usr/bin/python3.12", model="m"))
    assert be2._launch_args()[:2] == ["/usr/bin/python3.12", "-m"]


# ---- adopted / no-launch policy --------------------------------------------- #
def test_adopted_never_launches(monkeypatch):
    section = LlamaCppConfig(base_url="http://10.0.0.9:9999", binary="", model="m.gguf")
    be = _backend(LlamaCppBackend, section)
    assert be._adopted() is True
    assert be._base_url() == "http://10.0.0.9:9999"

    def _boom(*a, **kw):  # 任何拉起企图都必须失败
        raise AssertionError("adopted 模式不应拉起子进程")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)
    asyncio.run(be.ensure_started())  # 直接返回，不报错
    assert be._proc is None


def test_no_binary_never_launches(monkeypatch):
    be = _backend(LlamaCppBackend, LlamaCppConfig(model="m.gguf"))
    assert be._adopted() is False

    def _boom(*a, **kw):
        raise AssertionError("无 binary 时不应拉起子进程")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)
    asyncio.run(be.ensure_started())
    assert be._proc is None


def test_ensure_started_reuses_running_server(monkeypatch):
    # managed 配置但 /health 已 200（外部已跑）：不得重复拉起
    be = _backend(LlamaCppBackend, LlamaCppConfig(binary="llama-server", model="m.gguf"))

    def _boom(*a, **kw):
        raise AssertionError("服务已就绪时不应再拉起")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)
    asyncio.run(be.ensure_started())
    assert be._proc is None


def test_health_adopted_uses_mock():
    be = _backend(LlamaCppBackend, LlamaCppConfig(base_url="http://127.0.0.1:8081", model="m.gguf"))
    st = asyncio.run(be.health())
    assert st.healthy is True
    assert st.name == "llamacpp" and st.kind == "llamacpp"
    assert st.last_checked_at is not None


# ---- close ------------------------------------------------------------------- #
class _FakeProc:
    returncode = None

    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True

    async def wait(self):
        self.returncode = 0


def test_close_terminates_owned_process():
    be = _backend(LlamaCppBackend, LlamaCppConfig(binary="llama-server", model="m.gguf"))
    be._proc = _FakeProc()
    asyncio.run(be.close())
    assert be._proc is None
    assert be._client.is_closed


def test_close_adopted_process_not_killed():
    # adopted 模式从未拉起进程：close 只关客户端，不触碰任何进程
    be = _backend(VllmBackend, VllmConfig(base_url="http://127.0.0.1:8000", model="m"))
    asyncio.run(be.ensure_started())
    assert be._proc is None
    asyncio.run(be.close())
    assert be._proc is None
    assert be._client.is_closed
