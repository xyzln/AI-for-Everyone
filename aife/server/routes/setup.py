"""Setup (one-command deployment) endpoints (02-architecture §5.2, 05 §5.2)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...bootstrap import run_setup
from ...errors import AIEError, ErrorCode
from ...runtime import Runtime
from ..deps import get_rt
from ..schemas import SetupRunResponse, SetupStatusResponse, SetupStep

router = APIRouter(tags=["setup"])


class SetupRunRequest(BaseModel):
    steps: Optional[list[str]] = None
    skip: Optional[list[str]] = None
    dry_run: bool = False


@router.post("/setup/run", response_model=SetupRunResponse)
async def run(body: SetupRunRequest, rt: Runtime = Depends(get_rt)) -> SetupRunResponse:
    task = getattr(rt, "_setup_task", None)
    if task is not None and not task.done():
        raise AIEError(ErrorCode.SETUP_RUNNING, "部署正在进行中",
                      details={"current": getattr(rt, "last_setup", {}).get("current")})
    run_id = f"setup-{uuid.uuid4().hex[:8]}"

    async def _runner() -> None:
        await run_setup(
            rt, steps=body.steps, skip=body.skip, dry_run=body.dry_run, run_id=run_id
        )

    rt._setup_task = asyncio.create_task(_runner())
    return SetupRunResponse(run_id=run_id, status="running")


@router.get("/setup/status", response_model=SetupStatusResponse)
async def status(rt: Runtime = Depends(get_rt)) -> SetupStatusResponse:
    rec = getattr(rt, "last_setup", None)
    if not rec:
        return SetupStatusResponse.empty()
    return SetupStatusResponse(
        run_id=rec.get("run_id"),
        status=rec.get("status", "idle"),
        steps=[SetupStep(**s) for s in rec.get("steps", [])],
        current=rec.get("current"),
    )
