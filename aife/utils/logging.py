"""Structured JSONL logging with secret masking + trace/stage context.

Implements 04-data-model §2.4 (JSONL schema) and 05-api-contract §6.3/§10.1.
Stdlib only. A bounded bridge can forward ``log.line`` events to the WS bus
without creating an import dependency from utils -> server (05 §1.7 R4).
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|credential|authorization)"
)
URL_USERINFO_RE = re.compile(r"(?i)([a-z]+://)([^/@:]+):([^/@]+)@")


def mask_secrets(value: Any) -> Any:
    """Recursively mask secret-shaped values and URL userinfo (04 §6.3)."""
    if isinstance(value, str):
        value = URL_USERINFO_RE.sub(r"\1***:***@", value)
        if SECRET_RE.search(value):
            return "***"
        return value
    if isinstance(value, dict):
        return {k: ("***" if SECRET_RE.search(str(k)) else mask_secrets(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(mask_secrets(v) for v in value)
    return value


# Context carried across a request / run (architecture §5.1-3, data-model §2.4).
trace_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("aife_trace", default=None)
stage_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("aife_stage", default=None)
run_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("aife_run", default=None)


def set_trace(trace_id: Optional[str]) -> None:
    trace_ctx.set(trace_id)


def set_stage(stage: Optional[str]) -> None:
    stage_ctx.set(stage)


def set_run(run_id: Optional[str]) -> None:
    run_ctx.set(run_id)


class _AifeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{record.created % 1:06.3f}"[2:] + "Z"
        sdoc = getattr(record, "_aife_fields", None) or {}
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        tid = getattr(record, "_aife_trace", None) or trace_ctx.get()
        stage = getattr(record, "_aife_stage", None) or stage_ctx.get()
        run = getattr(record, "_aife_run", None) or run_ctx.get()
        if tid:
            payload["trace_id"] = tid
        if stage:
            payload["stage"] = stage
        if run:
            payload["run_id"] = run
        event = getattr(record, "_aife_event", None)
        if event:
            payload["event"] = event
        dur = getattr(record, "_aife_duration_ms", None)
        if dur is not None:
            payload["duration_ms"] = dur
        if sdoc:
            payload["extra"] = mask_secrets(sdoc)
        if record.exc_info and not event:
            payload["message"] = (
                payload["message"] + "\n" + "".join(traceback.format_exception(*record.exc_info))
            )
        return json.dumps(payload, ensure_ascii=False, default=str)


class StructuredLogger:
    """Thin wrapper that threads trace/stage/run + structured fields into records."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _emit(self, level: int, message: str, *, event: Optional[str], fields: Optional[dict],
              trace_id: Optional[str], duration_ms: Optional[float]) -> None:
        if not self._logger.isEnabledFor(level):
            return
        extra = {
            "_aife_event": event,
            "_aife_fields": fields or {},
            "_aife_trace": trace_id,
            "_aife_duration_ms": duration_ms,
        }
        self._logger.log(level, message, extra=extra)

    def debug(self, message: str, *, event: Optional[str] = None, fields: Optional[dict] = None,
              trace_id: Optional[str] = None, duration_ms: Optional[float] = None) -> None:
        self._emit(logging.DEBUG, message, event=event, fields=fields, trace_id=trace_id, duration_ms=duration_ms)

    def info(self, message: str, *, event: Optional[str] = None, fields: Optional[dict] = None,
             trace_id: Optional[str] = None, duration_ms: Optional[float] = None) -> None:
        self._emit(logging.INFO, message, event=event, fields=fields, trace_id=trace_id, duration_ms=duration_ms)

    def warning(self, message: str, *, event: Optional[str] = None, fields: Optional[dict] = None,
                trace_id: Optional[str] = None, duration_ms: Optional[float] = None) -> None:
        self._emit(logging.WARNING, message, event=event, fields=fields, trace_id=trace_id, duration_ms=duration_ms)

    def error(self, message: str, *, event: Optional[str] = None, fields: Optional[dict] = None,
              trace_id: Optional[str] = None, duration_ms: Optional[float] = None) -> None:
        self._emit(logging.ERROR, message, event=event, fields=fields, trace_id=trace_id, duration_ms=duration_ms)

    def exception(self, message: str, *, event: Optional[str] = None, fields: Optional[dict] = None,
                  trace_id: Optional[str] = None, duration_ms: Optional[float] = None) -> None:
        if not self._logger.isEnabledFor(logging.ERROR):
            return
        extra = {
            "_aife_event": event,
            "_aife_fields": fields or {},
            "_aife_trace": trace_id,
            "_aife_duration_ms": duration_ms,
        }
        self._logger.error(message, exc_info=True, extra=extra)


_loggers: dict[str, StructuredLogger] = {}
_log_lock = threading.Lock()


def get_logger(name: str) -> StructuredLogger:
    with _log_lock:
        if name not in _loggers:
            _loggers[name] = StructuredLogger(name)
        return _loggers[name]


# --- WS / event bus bridge (optional; runtime registers a sink) -----------------
_sink: Optional[Callable[[str, str, str, str], None]] = None
_sink_level = logging.INFO


def register_log_sink(callback: Optional[Callable[[str, str, str, str], None]], min_level: int = logging.INFO) -> None:
    """Register a callback(level_name, logger_name, message, ts_iso) for log.line events."""
    global _sink, _sink_level
    _sink = callback
    _sink_level = min_level


class _LogLineHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if _sink is None or record.levelno < _sink_level:
            return
        try:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{record.created % 1:06.3f}"[2:] + "Z"
            _sink(record.levelname, record.name, record.getMessage(), ts)
        except Exception:
            pass


_configured = False
_config_lock = threading.Lock()


def configure_logging(
    *,
    level: str = "info",
    console_level: str = "info",
    log_dir: Optional[Path] = None,
    app_file: str = "aife.log",
    rotate_max_mb: float = 10.0,
    rotate_backups: int = 5,
    jsonl: bool = True,
) -> None:
    """Install the JSON rotating file handler + console handler once."""
    global _configured
    with _config_lock:
        if _configured:
            return
        _configured = True

    root = logging.getLogger("aife")
    root.setLevel(logging.DEBUG)
    # avoid duplicate handlers across re-config
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = _AifeFormatter()

    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        fh = RotatingFileHandler(
            log_dir / app_file,
            maxBytes=int(rotate_max_mb * 1024 * 1024),
            backupCount=rotate_backups,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        fh.setLevel(logging.DEBUG)
        root.addHandler(fh)

    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    try:
        ch.setLevel(console_level.upper())
    except Exception:
        ch.setLevel(logging.INFO)
    root.addHandler(ch)

    # WS bridge handler (always attached; no-op until a sink is registered)
    bh = _LogLineHandler()
    bh.setLevel(logging.INFO)
    root.addHandler(bh)

    root.propagate = False
