# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ |

## Reporting a Vulnerability

If you find a security issue, please **do not** open a public issue for an actively
exploitable vulnerability. Instead, report it to the maintainer (open an issue labeled
`security`, or contact the repo owner privately). Include steps to reproduce and the
affected version. You should receive an acknowledgement within a few days.

## Security Model & Notes

AIE is a **local, single-user** deployment & operations plane for local LLMs. Its
threat model assumes a trusted local machine.

- **Local binding by default.** The server binds to `127.0.0.1` with **no
  authentication** (MVP, per design decision D10). Setting `server.host` to `0.0.0.0`
  exposes the API/UI to your network **without auth** — only do this on a trusted
  network, and understand the risk.
- **Secrets stay out of files.** Credentials (e.g. an OpenAI-compatible `api_key`) are
  referenced via `${VAR}` environment variables only and are never written to config or
  logs in plaintext. The `/api/config` view masks secret values.
- **No telemetry.** AIE collects nothing and makes no outbound calls except to the
  inference backends / model registry you configure.
- **Subprocess management is explicit.** AIE only launches inference binaries you
  configure (Ollama / `llama-server` / `vllm`); it never silently downloads or executes
  anything. Processes it started itself are stopped on exit; adopted (externally
  started) processes are never killed.
- **Errors don't leak internals.** API error responses never include stack traces;
  those go to logs only, correlated by `trace_id`.

## Hardening Recommendations

- Keep AIE bound to `127.0.0.1` unless you add authentication.
- Run as a normal (non-admin) user; AIE does not need elevated privileges.
- Review `config/aife.yaml` before sharing your `~/.aife` directory, and never commit
  real tokens.
