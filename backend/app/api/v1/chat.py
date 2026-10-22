"""对话接口：会话管理、模型参数、流式问答。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.chat import ChatRequest, MessageOut, SessionCreate, SessionOut, SessionUpdate
from app.schemas.common import ok
from app.services import chat_service

router = APIRouter(prefix="/chat", tags=["对话"])


@router.get("/models", summary="可用模型与默认推理参数")
def list_models(_: User = Depends(get_current_user)) -> dict:
    return ok(
        {
            "models": settings.available_models,
            "default_model": settings.llm_default_model,
            "defaults": {
                "temperature": settings.llm_temperature,
                "top_p": settings.llm_top_p,
                "max_tokens": settings.llm_max_tokens,
                "history_rounds": settings.llm_history_rounds,
                "top_k": settings.rag_top_k,
                "use_rerank": settings.rerank_enabled,
            },
            "limits": {
                "temperature": [0, 2],
                "top_p": [0.01, 1],
                "max_tokens": [16, 8192],
                "history_rounds": [0, 20],
                "top_k": [1, 20],
            },
        }
    )


@router.get("/sessions", summary="会话列表")
def list_sessions(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    sessions = chat_service.list_sessions(db, current_user.id)
    return ok([SessionOut.model_validate(item).model_dump(mode="json") for item in sessions])


@router.post("/sessions", summary="新建会话")
def create_session(
    payload: SessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = chat_service.create_session(db, current_user.id, payload)
    return ok(SessionOut.model_validate(session).model_dump(mode="json"), message="会话创建成功")


@router.patch("/sessions/{session_id}", summary="重命名/更新会话")
def update_session(
    session_id: int,
    payload: SessionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = chat_service.update_session(db, session_id, current_user.id, payload)
    return ok(SessionOut.model_validate(session).model_dump(mode="json"), message="更新成功")


@router.delete("/sessions/{session_id}", summary="删除会话")
def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    chat_service.delete_session(db, session_id, current_user.id)
    return ok(message="会话已删除")


@router.get("/sessions/{session_id}/messages", summary="会话消息列表")
def list_messages(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    messages = chat_service.list_messages(db, session_id, current_user.id)
    return ok([MessageOut.model_validate(item).model_dump(mode="json") for item in messages])


@router.post("/stream", summary="流式问答（SSE）")
def stream(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        chat_service.stream_answer(current_user.id, payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
