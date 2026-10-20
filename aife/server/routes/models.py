"""Model listing, catalog, pull, delete (02-architecture §5.2, 05 §5.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path as PathParam

from ...errors import AIEError, ErrorCode
from ...models.catalog import available_for_profile
from ...runtime import Runtime
from ..deps import get_model_manager, get_ollama_manager, get_rt
from ..schemas import (
    CatalogEntry, DeleteResponse, ModelsAvailableResponse,
    ModelsResponse, PullResponse,
)

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelsResponse)
async def list_models(rt: Runtime = Depends(get_rt)) -> ModelsResponse:
    try:
        models = await rt.model_manager.list_installed()
    except AIEError as exc:
        if exc.code in (ErrorCode.OLLAMA_UNAVAILABLE,):
            raise
        raise
    return ModelsResponse(models=models)


@router.get("/models/available", response_model=ModelsAvailableResponse)
async def available(rt: Runtime = Depends(get_rt)) -> ModelsAvailableResponse:
    entries = [CatalogEntry(**e) for e in available_for_profile(rt.resolved)]
    return ModelsAvailableResponse(models=entries)


@router.post("/models/pull", response_model=PullResponse, status_code=202)
async def pull(body: dict, rt: Runtime = Depends(get_rt)) -> PullResponse:
    name = (body or {}).get("name")
    if not name:
        raise AIEError(ErrorCode.MODEL_INVALID_NAME, "缺少模型名")
    try:
        task_id = rt.model_manager.pull(name)
    except AIEError:
        raise
    return PullResponse(task_id=task_id)


@router.delete("/models/{name}", response_model=DeleteResponse)
async def delete(
    name: str = PathParam(...), rt: Runtime = Depends(get_rt)
) -> DeleteResponse:
    await rt.model_manager.delete(name)
    return DeleteResponse(deleted=True, name=name)
