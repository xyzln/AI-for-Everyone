"""AIE (AI For Everyone) — one-command local-LLM deployment tool.

Public surface: version + the most reusable domain types. The FastAPI app,
server routes and any framework-specific helpers live under ``aife.server`` so
the domain layer (config / hardware / backends / ollama / models) never has to
import ``fastapi`` (architecture §1.3 R1, R3).
"""

from .errors import (
    AIEError,
    ErrorBody,
    ErrorCode,
    ErrorResponse,
    http_status_for,
)
from .config import AifeConfig, load_config, ensure_config

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "AIEError",
    "ErrorBody",
    "ErrorCode",
    "ErrorResponse",
    "http_status_for",
    "AifeConfig",
    "load_config",
    "ensure_config",
]
