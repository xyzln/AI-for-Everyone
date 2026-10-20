"""FastAPI application factory (02-architecture §5.2)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..runtime import get_runtime
from ..utils.paths import resource_root
from .errors import register_error_handlers
from .routes import ROUTERS
from .routes.v1_openai import register_v1_error_handlers
from .routes.v1_openai import router as v1_router
from .ws import router as ws_router

WEB_DIR = resource_root() / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    rt = get_runtime()
    app.state.start_time = datetime.now(timezone.utc)
    try:
        await rt.startup()
        yield
    finally:
        await rt.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AIE (AI For Everyone)",
        version=__version__,
        description="AI For Everyone — one-command local LLM deployment",
        lifespan=lifespan,
    )
    cfg = get_runtime().cfg
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.server.cors_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    app.include_router(ws_router)
    # OpenAI 兼容面（D21/D22）：不带 /api 前缀，错误用 OpenAI 信封
    app.include_router(v1_router, prefix="/v1")
    register_error_handlers(app)
    # 必须在统一错误处理器之后注册：非 /v1 路径委托回统一错误体
    register_v1_error_handlers(app)
    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app


# Module-level app for uvicorn: `aife.server.app:app`
app = create_app()
