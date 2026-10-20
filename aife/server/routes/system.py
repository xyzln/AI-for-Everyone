"""System info, hardware report, and config (GET/PATCH)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...config import AifeConfig
from ...errors import AIEError, ErrorCode
from ...hardware import build_report, resolve_profile
from ...runtime import Runtime
from ..deps import get_rt
from ..schemas import ConfigPatch, ConfigView, HardwareReport, SystemInfo

router = APIRouter(tags=["system"])


@router.get("/system", response_model=SystemInfo)
async def system(rt: Runtime = Depends(get_rt)) -> SystemInfo:
    return SystemInfo(
        version=rt.cfg.config_version and _version(),
        platform=rt.report.platform,
        python=rt.report.python,
        ollama_version=rt.manager.state.version,
        profile=rt.resolved.profile_id,
        active_backend=rt.registry.active,
        cpu_cores=rt.report.cpu_cores,
        system_ram_gb=rt.report.system_ram_gb,
    )


@router.get("/hardware", response_model=HardwareReport)
async def hardware(rt: Runtime = Depends(get_rt)) -> HardwareReport:
    return rt.report


@router.get("/config", response_model=ConfigView)
async def get_config(rt: Runtime = Depends(get_rt)) -> ConfigView:
    return ConfigView.from_config(rt.cfg)


@router.patch("/config", response_model=ConfigView)
async def patch_config(body: ConfigPatch, rt: Runtime = Depends(get_rt)) -> ConfigView:
    merged = rt.cfg.model_dump()
    for section, value in body.model_dump(exclude_none=True).items():
        if isinstance(value, dict):
            merged[section] = {**(merged.get(section) or {}), **value}
    try:
        new_cfg = AifeConfig.model_validate(merged)
    except Exception as exc:
        raise AIEError(ErrorCode.CONFIG_INVALID, f"配置校验失败: {exc}", details={"error": str(exc)})
    rt.cfg = new_cfg
    # re-resolve hardware profile if device changed
    rt.resolved = resolve_profile(explicit_device=new_cfg.hardware.device)
    rt.report = build_report(rt.resolved)
    return ConfigView.from_config(new_cfg)


def _version() -> str:
    from ... import __version__
    return __version__
