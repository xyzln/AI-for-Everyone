"""FastAPI dependency providers — resolve singletons from the runtime."""

from __future__ import annotations

from ..runtime import Runtime, get_runtime


def get_rt() -> Runtime:
    return get_runtime()


def get_registry():
    return get_runtime().registry


def get_model_manager():
    return get_runtime().model_manager


def get_ollama_manager():
    return get_runtime().manager
