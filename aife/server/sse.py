"""SSE frame helper (05-api-contract §5.4)."""

from __future__ import annotations

import json
from typing import Any


def sse_pack(event: str, data: dict[str, Any]) -> str:
    """Serialize one SSE frame: ``event: X\\ndata: J\\n\\n``."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
