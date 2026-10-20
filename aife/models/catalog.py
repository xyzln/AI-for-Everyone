"""Model catalog: device capability -> recommended tier/model (D8, 04-data-model §2.1.4).

``catalog_tier`` is computed by :func:`hardware.resolve_profile`; this module maps
the tier to a concrete Ollama tag and exposes the catalog used by
``GET /api/models/available``.
"""

from __future__ import annotations

from typing import Any, Optional

from ..hardware import ResolvedProfile
from ..utils.logging import get_logger

logger = get_logger("aife.models.catalog")

TIER_MODELS: dict[str, str] = {
    "1.5b": "qwen2.5:1.5b",
    "3b": "qwen2.5:3b",
    "7b": "qwen2.5:7b",
    "14b": "qwen2.5:14b",
}

# Built-in catalog for GET /api/models/available (single source of tier->tag).
CATALOG: list[dict[str, Any]] = [
    {"name": "qwen2.5:1.5b", "size_gb": 1.0, "min_ram_gb": 4,
     "tags": ["cpu", "low-ram"], "recommended_for": "RAM < 8GB / 低端办公机"},
    {"name": "qwen2.5:3b", "size_gb": 1.9, "min_ram_gb": 8,
     "tags": ["cpu", "balanced"], "recommended_for": "8–16GB RAM（CPU 默认档）"},
    {"name": "qwen2.5:7b", "size_gb": 4.4, "min_ram_gb": 16,
     "tags": ["cpu", "gpu"], "recommended_for": "16–32GB RAM / 8–12GB VRAM"},
    {"name": "qwen2.5:14b", "size_gb": 8.7, "min_ram_gb": 32,
     "tags": ["cpu", "gpu", "high-end"], "recommended_for": "≥32GB RAM / ≥12GB VRAM"},
]


def catalog_model_for_tier(tier: Optional[str]) -> Optional[str]:
    if not tier:
        return None
    return TIER_MODELS.get(tier)


def recommend(resolved: ResolvedProfile) -> Optional[str]:
    return catalog_model_for_tier(resolved.catalog_tier)


def available_for_profile(resolved: Optional[ResolvedProfile] = None) -> list[dict[str, Any]]:
    """Return catalog entries, marking the one recommended for this profile."""
    rec = recommend(resolved) if resolved else None
    out = []
    for entry in CATALOG:
        e = dict(entry)
        e["recommended"] = (entry["name"] == rec)
        out.append(e)
    # Put the recommended one first.
    out.sort(key=lambda x: (not x["recommended"], x["min_ram_gb"]))
    return out
