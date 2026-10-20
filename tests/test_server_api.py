"""Server API contract tests (08-test-acceptance §api).

Uses the shared ``client`` fixture: a FastAPI TestClient wired to a runtime whose
Ollama is mocked (healthy + default model installed). No GPU / network needed.
"""

import json


def _parse_sse(text):
    out = []
    for frame in text.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        ev = None
        data = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                ev = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        if data:
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                pass
        out.append((ev, data))
    return out


def test_health_liveness(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body and "uptime_s" in body


def test_health_deep(client):
    r = client.get("/api/health/deep")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["healthy"], bool)
    assert isinstance(body["checks"], dict)


def test_system(client):
    r = client.get("/api/system")
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] == "cpu"  # this machine has no GPU
    assert "version" in body and "active_backend" in body


def test_hardware(client):
    r = client.get("/api/hardware")
    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["profile_id"] == "cpu"
    assert isinstance(body["devices"], list)


def test_models_list(client):
    r = client.get("/api/models")
    assert r.status_code == 200
    names = [m["name"] for m in r.json()["models"]]
    assert "qwen2.5:3b" in names


def test_models_available(client):
    r = client.get("/api/models/available?device_profile=cpu")
    assert r.status_code == 200
    assert isinstance(r.json()["models"], list)


def test_backends(client):
    r = client.get("/api/backends")
    assert r.status_code == 200
    body = r.json()
    assert body["active"]
    assert "ollama" in body["backends"]


def test_config_get_masked(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert "ollama" in body and "server" in body


def test_chat_non_streaming(client):
    r = client.post("/api/chat", json={
        "model": "qwen2.5:3b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["message"]["content"] == "Hello"
    assert body["done"] is True


def test_chat_streaming(client):
    r = client.post("/api/chat/stream", json={
        "model": "qwen2.5:3b",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    })
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    events = _parse_sse(r.text)
    evs = [e for (e, _) in events]
    assert "delta" in evs
    assert "done" in evs


def test_chat_validation_error_mapped(client):
    # invalid "messages" type -> FastAPI 422 -> our handler maps to 400 VALIDATION
    r = client.post("/api/chat", json={"model": "qwen2.5:3b", "messages": "not-a-list"})
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "VALIDATION"
    assert "details" in body["error"]


def test_setup_status(client):
    r = client.get("/api/setup/status")
    assert r.status_code == 200
    assert "status" in r.json()
