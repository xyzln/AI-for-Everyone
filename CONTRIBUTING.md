# Contributing to AIE

Thanks for your interest in improving AI For Everyone! This document covers how to set
up a dev environment, run the tests, and the conventions to follow.

## Dev setup

- Python **3.10 – 3.12**.
- Create a virtual environment and install in editable mode:

  ```bash
  python -m venv .venv
  # Windows: .venv\Scripts\activate    |  macOS/Linux: source .venv/bin/activate
  pip install -e ".[dev]"        # core + pytest
  pip install -e ".[desktop]"    # optional: native desktop window (pywebview + pystray)
  ```

## Running the tests

The full suite runs **without a GPU, without Ollama, and without network** (Ollama is
mocked via `httpx.MockTransport`):

```bash
pytest -q
```

Please keep it that way — new tests should not require real hardware or the network.

## Project layout

| Path | What |
|------|------|
| `aife/` | Backend: `config`, `hardware`, `ollama/`, `backends/`, `models/`, `runtime`, `bootstrap`, `server/`, `cli`, `desktop` |
| `web/` | Zero-build native ESM frontend (no npm / bundler / framework) |
| `scripts/` | Platform install scripts, packaging, and desktop-app build scripts |
| `tests/` | pytest suite |
| `docs/design/` | Requirements, architecture, API contract, packaging, test-acceptance |

## Conventions

- **Core dependencies ≤ 6**: `fastapi`, `uvicorn`, `httpx`, `pydantic`, `PyYAML`,
  `websockets`. `torch` is lazy-only (hardware probing) — never a hard dependency.
- **Layering**: the domain layer (`config` / `hardware` / `backends` / `models`) must
  not import `fastapi` or any web framework. `runtime.py` is the single composition
  root.
- **Errors**: all responses are pydantic models; errors use the unified envelope
  `{"error": {code, message, details, trace_id}}` on `/api/*`, and the OpenAI envelope
  on `/v1/*`.
- **Adding a backend**: subclass `LLMBackend` (or `ManagedServerBackend` for
  OpenAI-compatible servers) and register it in `runtime.py`.
- **Commits**: concise, present-tense messages.

## Desktop app

```bash
pip install -e ".[desktop]"
aife desktop          # native window (WebView2/WKWebView/GTK); falls back to browser
```

Windows builds a windowed exe via `packaging/aife_desktop.spec`; macOS/Linux build on
the target OS with `scripts/build-desktop-macos.sh` / `scripts/build-desktop-linux.sh`.

## Questions

Open an issue — feedback and PRs are welcome.
