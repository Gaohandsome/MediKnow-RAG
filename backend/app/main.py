"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db.session import init_db
from app.schemas.common import ok


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    logger.info(f"启动 {settings.app_name}（env={settings.app_env}）")
    issues = settings.insecure_defaults
    if issues:
        message = f"配置自检未通过：{'、'.join(issues)} 仍为空或示例值，请参照 .env.example 填写"
        if settings.app_env == "dev":
            logger.warning(message)
        else:
            raise RuntimeError(message)
    try:
        init_db()
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"数据库初始化失败：{exc}")
    yield
    logger.info("服务已停止")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="基于企业内容知识的问答系统（RAG）",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)

    # 本地媒体目录（解析阶段裁出的表格/流程图），供前端直接展示
    if settings.media_storage == "local":
        media_dir = settings.media_path
        media_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            settings.media_url_prefix,
            StaticFiles(directory=str(media_dir)),
            name="media",
        )
        logger.info(f"媒体目录已挂载：{settings.media_url_prefix} -> {media_dir}")

    @app.get("/", tags=["系统"], summary="健康检查")
    def health() -> dict:
        return ok({"status": "ok", "app": settings.app_name, "version": "1.0.0"})

    return app


app = create_app()
