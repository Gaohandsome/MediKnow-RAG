"""知识库接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ok
from app.schemas.knowledge import (
    KnowledgeBaseCreate,
    KnowledgeBaseOption,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
)
from app.services import knowledge_service

router = APIRouter(prefix="/knowledge-bases", tags=["知识库"])


@router.get("", summary="知识库列表")
def list_knowledge_bases(
    keyword: str | None = Query(default=None, description="按名称搜索"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = knowledge_service.list_knowledge_bases(db, current_user.id, keyword)
    return ok([KnowledgeBaseOut.model_validate(item).model_dump(mode="json") for item in items])


@router.get("/options", summary="知识库下拉选项")
def knowledge_base_options(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    items = knowledge_service.list_knowledge_bases(db, current_user.id)
    return ok([KnowledgeBaseOption.model_validate(item).model_dump(mode="json") for item in items])


@router.post("", summary="创建知识库")
def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    kb = knowledge_service.create_knowledge_base(db, current_user.id, payload)
    return ok(KnowledgeBaseOut.model_validate(kb).model_dump(mode="json"), message="知识库创建成功")


@router.get("/{kb_id}", summary="知识库详情")
def get_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    kb = knowledge_service.get_knowledge_base(db, kb_id, current_user.id)
    return ok(KnowledgeBaseOut.model_validate(kb).model_dump(mode="json"))


@router.patch("/{kb_id}", summary="更新知识库")
def update_knowledge_base(
    kb_id: int,
    payload: KnowledgeBaseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    kb = knowledge_service.update_knowledge_base(db, kb_id, current_user.id, payload)
    return ok(KnowledgeBaseOut.model_validate(kb).model_dump(mode="json"), message="更新成功")


@router.delete("/{kb_id}", summary="删除知识库")
def delete_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    knowledge_service.delete_knowledge_base(db, kb_id, current_user.id)
    return ok(message="知识库已删除")
