"""日志配置：同时输出到控制台和按天切分的文件。"""
from __future__ import annotations

import sys

from loguru import logger

from app.core.config import settings

_configured = False


def setup_logging() -> None:
    """初始化日志（重复调用只生效一次）。"""
    global _configured
    if _configured:
        return

    logger.remove()
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # 控制台
    logger.add(sys.stderr, level=settings.log_level, format=fmt, enqueue=True, backtrace=True)

    # 文件（按天切分，保留 14 天）
    logger.add(
        str(settings.log_path / "app_{time:YYYY-MM-DD}.log"),
        level=settings.log_level,
        format=fmt,
        rotation="00:00",
        retention="14 days",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )
    _configured = True
    logger.info(f"日志初始化完成，目录：{settings.log_path}")


def get_logger(name: str = "app"):
    return logger.bind(module=name)
