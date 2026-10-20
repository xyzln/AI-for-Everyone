"""Health & deep-health (02-architecture §5.2, 05 §5.2)."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from ... import __version__
from ...models.catalog import recommend
from ...runtime import Runtime
from ..deps import get_rt
from ..schemas import HealthCheck, HealthReportResp, Liveness

router = APIRouter(tags=["health"])


def _uptime_s(request: Request) -> float:
    start = getattr(request.app.state, "start_time", None)
    if start is None:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - start).total_seconds())


def _disk_free_gb() -> float:
    try:
        total, used, free = shutil.disk_usage(Path.home())
        return round(free / (1024 ** 3), 1)
    except Exception:
        return 0.0


@router.get("/health", response_model=Liveness)
async def health(request: Request, rt: Runtime = Depends(get_rt)) -> Liveness:
    return Liveness(version=__version__, uptime_s=_uptime_s(request))


@router.get("/health/deep", response_model=HealthReportResp)
async def health_deep(request: Request, rt: Runtime = Depends(get_rt)) -> HealthReportResp:
    checks: dict[str, HealthCheck] = {}

    checks["aife"] = HealthCheck(name="aife", ok=True, detail=f"AIE v{__version__}")

    ollama_ok = await rt.manager.is_healthy()
    checks["ollama"] = HealthCheck(
        name="ollama",
        ok=ollama_ok,
        detail=(rt.manager.state.version or ("不可达" if not ollama_ok else "")),
        severity="error" if not ollama_ok else "ok",
    )

    model = rt.cfg.models.default or recommend(rt.resolved)
    model_ok = True
    model_detail = "无需默认模型" if not model else f"默认模型 {model}"
    if model:
        try:
            names = [m.get("name") for m in await rt.manager.client.tags()]
            if model not in names:
                model_ok = False
                model_detail = f"默认模型 {model} 未安装"
        except Exception:
            model_ok = False
            model_detail = "无法获取模型列表"
    checks["models"] = HealthCheck(
        name="models", ok=model_ok, detail=model_detail,
        severity="warn" if not model_ok else "ok",
    )

    backend = rt.registry.current()
    backend_ok = True
    backend_detail = "无活跃后端"
    if backend is not None:
        st = await backend.health()
        backend_ok = st.healthy
        backend_detail = st.detail
    checks["backend"] = HealthCheck(
        name="backend", ok=backend_ok, detail=backend_detail,
        severity="error" if not backend_ok else "ok",
    )

    free = _disk_free_gb()
    disk_ok = free >= 1.0
    checks["disk"] = HealthCheck(
        name="disk", ok=disk_ok, detail=f"剩余空间 {free:.1f} GiB",
        severity="warn" if not disk_ok else "ok",
    )

    healthy = all(c.ok for c in checks.values())
    return HealthReportResp(
        healthy=healthy, checks=checks,
        version=__version__, uptime_s=_uptime_s(request),
    )
