"""Ollama protocol client: NDJSON parse + error mapping (mocked HTTP)."""

import asyncio

import httpx
import pytest

from aife.ollama.protocol import OllamaClient, OllamaProtocolError


def _client(handler):
    return OllamaClient("http://ollama.local", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_version_and_tags():
    def h(req):
        if req.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.5.7"})
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "x"}]})
        return httpx.Response(404)

    async def run():
        c = _client(h)
        assert await c.version() == "0.5.7"
        assert (await c.tags())[0]["name"] == "x"
        await c.aclose()

    asyncio.run(run())


def test_chat_stream_parse():
    def h(req):
        if req.url.path == "/api/chat":
            return httpx.Response(
                200,
                text='{"message":{"content":"hi"},"done":false}\n{"done":true,"usage":{"prompt_tokens":1}}\n',
            )
        return httpx.Response(404)

    async def run():
        c = _client(h)
        chunks = [o async for o in c.chat(model="m", messages=[])]
        assert chunks[0]["message"]["content"] == "hi"
        assert chunks[-1]["done"] is True
        await c.aclose()

    asyncio.run(run())


def test_pull_progress_callback():
    calls = []

    def h(req):
        return httpx.Response(
            200, text='{"status":"pulling","completed":50,"total":100}\n{"status":"success"}\n'
        )

    async def run():
        c = _client(h)
        await c.pull("m", progress=lambda s, c, t: calls.append((s, c, t)))
        assert calls and calls[0] == ("pulling", 50, 100)
        await c.aclose()

    asyncio.run(run())


def test_delete():
    def h(req):
        if req.url.path == "/api/delete":
            return httpx.Response(200, json={"status": "success"})
        return httpx.Response(404)

    async def run():
        c = _client(h)
        await c.delete("m")  # should not raise
        await c.aclose()

    asyncio.run(run())


def test_error_mapping_on_bad_status():
    def h(req):
        return httpx.Response(500, text="boom")

    async def run():
        c = _client(h)
        with pytest.raises(OllamaProtocolError):
            await c.version()
        await c.aclose()

    asyncio.run(run())
