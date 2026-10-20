"""One-command deployment pipeline (aife setup).

Implements requirement #1: a staged, skippable flow —
  deps → ollama → model → verify
each stage emits progress via the runtime event bus (WS/SSE) and leaves a
machine-readable step record. Failures record a remedy and stop the pipeline
(never silent-exit). Stage ``--skip-*`` is honored (02-architecture §1.2).
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .errors import AIEError, ErrorCode
from .models.catalog import recommend
from .utils.logging import get_logger

logger = get_logger("aife.bootstrap")

STAGE_ORDER = ["deps", "ollama", "model", "verify"]
VALID_SKIP = {"deps", "ollama", "model"}


class SetupError(Exception):
    def __init__(self, stage: str, message: str, remedy: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.remedy = remedy


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def run_setup(
    rt,
    *,
    steps: Optional[list[str]] = None,
    skip: Optional[list[str]] = None,
    dry_run: bool = False,
    on_event: Optional[Callable[[str, dict], None]] = None,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    """Run the deployment pipeline. Returns a run record (also emitted as events)."""
    run_id = run_id or f"setup-{uuid.uuid4().hex[:8]}"
    order = steps or STAGE_ORDER
    skip_set = set(skip or []) | set(rt.cfg.setup.skip)
    skip_set &= VALID_SKIP

    record: dict[str, Any] = {
        "run_id": run_id,
        "status": "running",
        "steps": [],
        "current": None,
    }

    def _emit(etype: str, payload: dict[str, Any]) -> None:
        rt.publish(etype, payload)
        if on_event:
            on_event(etype, payload)

    _emit("setup.started", {"run_id": run_id, "steps": order})

    try:
        for stage in order:
            if stage in skip_set:
                rec = {"name": stage, "status": "skipped",
                       "started_at": _now(), "finished_at": _now()}
                record["steps"].append(rec)
                _emit("setup.step_done", {"run_id": run_id, "step": stage,
                                          "duration_ms": 0, "skipped": True})
                continue

            rec = {"name": stage, "status": "running",
                   "started_at": _now(), "finished_at": None}
            record["steps"].append(rec)
            record["current"] = stage
            _emit("setup.step_progress", {"run_id": run_id, "step": stage,
                                          "message": f"开始阶段 {stage}"})

            started = datetime.now(timezone.utc)
            try:
                if stage == "deps":
                    await _stage_deps(rt, dry_run, _emit, run_id)
                elif stage == "ollama":
                    await _stage_ollama(rt, dry_run, _emit, run_id)
                elif stage == "model":
                    await _stage_model(rt, dry_run, _emit, run_id)
                elif stage == "verify":
                    await _stage_verify(rt, dry_run, _emit, run_id)

                dur = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
                rec["status"] = "done"
                rec["finished_at"] = _now()
                _emit("setup.step_done", {"run_id": run_id, "step": stage, "duration_ms": dur})
            except SetupError as exc:
                rec["status"] = "failed"
                rec["finished_at"] = _now()
                rec["error"] = {"stage": exc.stage, "message": str(exc), "remedy": exc.remedy}
                record["status"] = "failed"
                record["current"] = None
                _emit("setup.error", {"run_id": run_id, "step": exc.stage,
                                      "code": "SETUP_FAILED", "message": str(exc),
                                      "remedy": exc.remedy})
                break
            except AIEError as exc:
                rec["status"] = "failed"
                rec["finished_at"] = _now()
                rec["error"] = {"stage": stage, "message": exc.message,
                                "code": exc.code.value if hasattr(exc.code, "value") else str(exc.code)}
                record["status"] = "failed"
                _emit("setup.error", {"run_id": run_id, "step": stage,
                                      "code": rec["error"]["code"], "message": exc.message})
                break

        if record["status"] == "running":
            record["status"] = "done"
        record["current"] = None
        return record
    finally:
        # store latest record for GET /api/setup/status
        rt.last_setup = record  # type: ignore[attr-defined]


# ---- stages ---------------------------------------------------------------- #
async def _stage_deps(rt, dry_run: bool, emit, run_id) -> None:
    emit("setup.step_progress", {"run_id": run_id, "step": "deps",
                                 "message": "检查 Python 与核心依赖"})
    if sys.version_info < (3, 10):
        raise SetupError("deps", f"Python >=3.10 需要，当前 {sys.version.split()[0]}",
                         remedy="请升级 Python 到 3.10+ 后重试")
    core = ["fastapi", "uvicorn", "httpx", "pydantic", "yaml", "websockets"]
    missing = []
    for mod in core:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        raise SetupError("deps", f"缺少依赖: {', '.join(missing)}",
                         remedy=f"运行：pip install {' '.join(missing)}")
    if dry_run:
        emit("setup.step_progress", {"run_id": run_id, "step": "deps",
                                     "message": "（dry-run）依赖检查通过"})


async def _stage_ollama(rt, dry_run: bool, emit, run_id) -> None:
    emit("setup.step_progress", {"run_id": run_id, "step": "ollama",
                                 "message": "检查 Ollama 安装与版本"})
    if dry_run:
        emit("setup.step_progress", {"run_id": run_id, "step": "ollama",
                                     "message": "（dry-run）将检测/拉起 Ollama"})
        return
    if not rt.manager.is_installed():
        method = rt.cfg.ollama.install.method
        from .utils.platform import is_macos, is_windows
        if is_windows():
            hint = "winget install Ollama.Ollama  或访问 https://ollama.com/download"
        elif is_macos():
            hint = "brew install ollama"
        else:
            hint = "curl -fsSL https://ollama.com/install.sh | sh"
        raise SetupError(
            "ollama", "未检测到 Ollama 可执行文件",
            remedy=f"请先安装 Ollama：\n  {hint}\n（当前安装方式配置：{method}）",
        )
    await rt.manager.ensure_started()
    ok, remedy = rt.manager.check_version()
    if not ok:
        raise SetupError("ollama", remedy or "Ollama 版本过低", remedy=remedy or "")
    emit("setup.step_progress", {"run_id": run_id, "step": "ollama",
                                 "message": f"Ollama {rt.manager.state.version} 就绪"})


async def _stage_model(rt, dry_run: bool, emit, run_id) -> None:
    model = rt.cfg.models.default or recommend(rt.resolved)
    if not model:
        raise SetupError("model", "无法确定默认模型（catalog_tier 为空）")
    emit("setup.step_progress", {"run_id": run_id, "step": "model",
                                 "message": f"准备模型 {model}"})
    if dry_run:
        emit("setup.step_progress", {"run_id": run_id, "step": "model",
                                     "message": f"（dry-run）将拉取 {model}"})
        return
    if not await rt.manager.is_healthy():
        raise SetupError("model", "Ollama 未就绪，无法拉取模型",
                         remedy="请先完成 ollama 阶段")
    # kick off pull (ModelManager publishes model.pull_progress / model.pull_done)
    try:
        rt.model_manager.pull(model)
    except AIEError as exc:
        if exc.code == ErrorCode.PULL_IN_PROGRESS:
            pass
        else:
            raise SetupError("model", exc.message)
    # poll until installed (best-effort, bounded)
    for _ in range(600):
        try:
            names = [m.get("name") for m in await rt.manager.client.tags()]
            if model in names:
                emit("setup.step_progress", {"run_id": run_id, "step": "model",
                                             "message": f"模型 {model} 已安装"})
                return
        except Exception:
            pass
        await asyncio.sleep(2)
    raise SetupError("model", f"模型 {model} 拉取超时",
                     remedy="请检查网络后重试，或在 UI 模型页手动拉取")


async def _stage_verify(rt, dry_run: bool, emit, run_id) -> None:
    emit("setup.step_progress", {"run_id": run_id, "step": "verify",
                                 "message": "执行深度健康检查"})
    if dry_run:
        emit("setup.step_progress", {"run_id": run_id, "step": "verify",
                                     "message": "（dry-run）跳过实际健康检查"})
        return
    ok, detail = await _deep_check(rt)
    if not ok:
        raise SetupError("verify", detail,
                         remedy="查看上方状态页 /api/health/deep 了解未通过项")
    emit("setup.step_progress", {"run_id": run_id, "step": "verify",
                                 "message": "部署完成，本地 LLM 服务可用"})


async def _deep_check(rt) -> tuple[bool, str]:
    if not await rt.manager.is_healthy():
        return False, "Ollama 不可达"
    model = rt.cfg.models.default or recommend(rt.resolved)
    if model:
        names = [m.get("name") for m in await rt.manager.client.tags()]
        if model not in names:
            return False, f"默认模型 {model} 未安装"
    return True, "ok"
