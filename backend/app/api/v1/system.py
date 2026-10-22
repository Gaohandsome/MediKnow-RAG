"""系统级接口：向前端暴露医疗安全层文案与开关。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.schemas.common import ok
from app.services.cache import cache_health
from app.services.llm import probe_models
from app.services.qa_cache import hot_questions, stats as qa_stats
from app.services.safety import disclaimer_text

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/safety-config", summary="获取医疗安全层配置")
def get_safety_config() -> dict:
    """返回免责声明等文案，供前端在历史消息回看时统一渲染。"""
    return ok(
        {
            "app_name": settings.app_name,
            "disclaimer": disclaimer_text(),
            "disclaimer_enabled": settings.medical_disclaimer_enabled,
            "red_flag_enabled": settings.safety_red_flag_enabled,
            "refuse_when_no_context": settings.safety_refuse_when_no_context,
        }
    )


@router.get("/cache-status", summary="缓存后端状态")
def get_cache_status(db: Session = Depends(get_db)) -> dict:
    """Redis 未启用或连不上时会自动降级为进程内缓存，这里如实反映。"""
    try:
        qa = qa_stats(db)
    except Exception:  # noqa: BLE001
        qa = {}
    return ok(
        {
            **cache_health(),
            "enabled": settings.qa_cache_enabled,
            "threshold": settings.qa_cache_threshold,
            "qa": qa,
        }
    )


@router.get("/qa-stats", summary="高频问答统计")
def get_qa_stats(limit: int = Query(default=10, ge=1, le=50), db: Session = Depends(get_db)) -> dict:
    """统计高频问答对（缓存命中次数排序）。"""
    return ok({"items": hot_questions(db, limit)})


@router.get("/llm-status", summary="大模型可用性自检")
def get_llm_status(force: bool = Query(default=False, description="跳过 60 秒缓存，立即重新探测")) -> dict:
    """逐个试探候选模型，排查 403 未授权 / 欠费。结果缓存 60 秒。"""
    try:
        return ok(probe_models(force=force))
    except Exception as exc:  # noqa: BLE001
        return ok({"any_available": False, "detail": str(exc)[:300], "candidates": []})
