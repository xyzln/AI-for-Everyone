"""Backend registry endpoints (05 §5.2)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...errors import AIEError, ErrorCode
from ...runtime import Runtime
from ..deps import get_rt
from ..schemas import (
    RegistrySnapshot, SelectBackendResponse,
)

router = APIRouter(tags=["backends"])


class SelectBackendRequest(BaseModel):
    name: str
    force: bool = False


@router.get("/backends", response_model=RegistrySnapshot)
async def list_backends(rt: Runtime = Depends(get_rt)) -> RegistrySnapshot:
    return await rt.registry.snapshot()


@router.post("/backends/select", response_model=SelectBackendResponse)
async def select(body: SelectBackendRequest, rt: Runtime = Depends(get_rt)) -> SelectBackendResponse:
    if body.name not in rt.registry._backends:
        raise AIEError(ErrorCode.BACKEND_UNKNOWN, f"未知后端: {body.name}")
    if not body.force:
        st = await rt.registry.get(body.name).health()
        if not st.healthy:
            raise AIEError(ErrorCode.BACKEND_UNHEALTHY, st.detail or "后端不健康")
    rt.registry.switch_to(body.name, "manual")
    rt.publish("backend.changed", {"active": body.name, "reason": "manual"})
    return SelectBackendResponse(active=body.name)
