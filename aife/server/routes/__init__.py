"""Route aggregation."""

from . import backends, chat, health, models, ollama, setup, system

ROUTERS = [
    health.router,
    system.router,
    models.router,
    chat.router,
    backends.router,
    setup.router,
    ollama.router,
]

__all__ = ["ROUTERS"]
