"""FastAPI 应用组装。路由按模块注册；缺失模块通过软导入容错，便于并行开发。"""
from __future__ import annotations

import importlib
import logging
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import models  # noqa: F401
from .core.config import APP_NAME, APP_VERSION, CORS_ORIGINS, LLM_API_KEY, LLM_MODEL, STATIC_DIR
from .core.db import init_db

log = logging.getLogger("dataclaw")
_started = time.time()

ROUTER_MODULES: list[str] = [
    "auth", "users", "templates", "employees", "public_agents", "skills",
    "sessions", "artifacts", "files", "knowledge", "datasources", "policies",
    "channels", "audit", "overview", "metrics",
]


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    init_db()

    for name in ROUTER_MODULES:
        try:
            mod = importlib.import_module(f".api.{name}", package="app")
        except ModuleNotFoundError as exc:
            log.warning("router %s 未实现/缺少依赖: %s", name, exc)
            continue
        router = getattr(mod, "router", None)
        if router is None:
            log.warning("模块 app.api.%s 未导出 router", name)
            continue
        app.include_router(router, prefix="/api")
        log.info("已注册路由 /api <- %s", name)

    @app.on_event("startup")
    def _startup() -> None:
        try:
            from .seed import ensure_seed
            ensure_seed()
        except Exception as exc:  # 种子失败不阻止启动
            log.warning("seed 跳过: %s", exc)

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "name": APP_NAME,
            "version": APP_VERSION,
            "llm": f"provider:{LLM_MODEL}" if LLM_API_KEY else "offline-planner",
            "uptime": round(time.time() - _started, 1),
        }

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(_request, exc: StarletteHTTPException):  # noqa: ANN001
        detail = exc.detail
        if isinstance(detail, dict):
            body = {"error": detail}
        else:
            body = {"error": {"code": f"HTTP_{exc.status_code}", "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=body)

    # 生产形态：前端构建产物由同端口托管；前端路由回退到 index.html
    if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            target = STATIC_DIR / full_path
            if full_path and target.is_file():
                return FileResponse(target)
            return FileResponse(STATIC_DIR / "index.html")
    else:
        @app.get("/")
        def root() -> dict:
            return {"service": APP_NAME, "docs": "/api/docs", "hint": "前端未构建：pnpm --dir frontend build"}

    return app


app = create_app()
