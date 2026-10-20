"""Ollama lifecycle ops (restart) — operational endpoint (05 §5.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...errors import AIEError, ErrorCode
from ...runtime import Runtime
from ..deps import get_rt
from ..schemas import RestartResponse

router = APIRouter(tags=["ollama"])


@router.post("/ollama/restart", response_model=RestartResponse)
async def restart(rt: Runtime = Depends(get_rt)) -> RestartResponse:
    if not rt.manager.is_installed():
        raise AIEError(ErrorCode.OLLAMA_UNAVAILABLE, "Ollama 未安装，无法重启")
    await rt.manager.restart()
    rt.publish("health.changed", {"healthy": False, "failed_checks": ["ollama"]})
    return RestartResponse(restarted=True)
