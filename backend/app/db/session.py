"""数据库连接与会话管理。"""
from __future__ import annotations

from collections.abc import Generator

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=20,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ensure_database() -> None:
    """MySQL 库不存在时自动创建。"""
    server_engine = create_engine(settings.server_url, isolation_level="AUTOCOMMIT", future=True)
    with server_engine.connect() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_database}` "
                f"DEFAULT CHARACTER SET {settings.mysql_charset} COLLATE {settings.mysql_charset}_general_ci"
            )
        )
    server_engine.dispose()


def init_db() -> None:
    """建库 + 建表。"""
    # 确保所有模型已被导入注册
    from app import models  # noqa: F401

    ensure_database()
    Base.metadata.create_all(bind=engine)
    logger.info(f"数据库初始化完成：{settings.mysql_database}")
