"""知识库服务：创建、查询、更新、删除。"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BizError
from app.models.document import Document, DocumentChunk
from app.models.knowledge import KnowledgeBase
from app.schemas.knowledge import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services.vector_store import get_vector_store


def _get_owned(db: Session, kb_id: int, user_id: int) -> KnowledgeBase:
    """写操作用：必须是自己的库。"""
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None or kb.user_id != user_id:
        raise BizError("知识库不存在或无权访问", status_code=404)
    return kb


def get_readable(db: Session, kb_id: int, user_id: int) -> KnowledgeBase:
    """读操作用：共享模式下不限所有者，只要求库存在。

    写操作（改名 / 删除 / 上传 / 重解析）仍然走 `_get_owned`，
    否则同事就能改动别人的知识库。
    """
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise BizError("知识库不存在", status_code=404)
    if not settings.kb_shared_read and kb.user_id != user_id:
        raise BizError("知识库不存在或无权访问", status_code=404)
    return kb


def create_knowledge_base(db: Session, user_id: int, payload: KnowledgeBaseCreate) -> KnowledgeBase:
    """创建知识库，并在 Milvus 中建立对应集合。"""
    duplicated = db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.user_id == user_id, KnowledgeBase.name == payload.name
        )
    )
    if duplicated:
        raise BizError("同名知识库已存在，请更换名称", status_code=409)

    kb = KnowledgeBase(
        user_id=user_id,
        name=payload.name,
        description=payload.description,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
        retrieval_mode=payload.retrieval_mode,
        collection_name="pending",
    )
    db.add(kb)
    db.flush()

    kb.collection_name = get_vector_store().collection_name(kb.id)
    db.flush()

    # 所有知识库共用同一个集合，这里只保证集合存在（不会覆盖已有数据）
    get_vector_store().ensure_collection(kb.collection_name, kb.retrieval_mode)
    logger.info(f"知识库创建成功：id={kb.id} name={kb.name} mode={kb.retrieval_mode}")
    return kb


def list_knowledge_bases(db: Session, user_id: int, keyword: str | None = None) -> list[KnowledgeBase]:
    """列出可见的知识库。

    `KB_SHARED_READ=true` 时返回全部（院内资料全院共用），否则只看自己的。
    """
    stmt = select(KnowledgeBase)
    if not settings.kb_shared_read:
        stmt = stmt.where(KnowledgeBase.user_id == user_id)
    if keyword:
        stmt = stmt.where(KnowledgeBase.name.like(f"%{keyword.strip()}%"))
    return list(db.scalars(stmt.order_by(KnowledgeBase.updated_at.desc())))


def get_knowledge_base(db: Session, kb_id: int, user_id: int) -> KnowledgeBase:
    return _get_owned(db, kb_id, user_id)


def get_readable_knowledge_base(db: Session, kb_id: int, user_id: int) -> KnowledgeBase:
    return get_readable(db, kb_id, user_id)


def update_knowledge_base(
    db: Session, kb_id: int, user_id: int, payload: KnowledgeBaseUpdate
) -> KnowledgeBase:
    kb = _get_owned(db, kb_id, user_id)
    if payload.name is not None:
        kb.name = payload.name.strip()
    if payload.description is not None:
        kb.description = payload.description
    db.flush()
    return kb


def delete_knowledge_base(db: Session, kb_id: int, user_id: int) -> None:
    """删除知识库：先按 kb_id 清理集合中的向量，再删数据库记录（集合本身共用，不删除）。"""
    kb = _get_owned(db, kb_id, user_id)
    store = get_vector_store()
    collection = store.collection_name()
    db.delete(kb)
    db.flush()
    try:
        if store.has_collection(collection):
            store.delete_by_filter(collection, f"kb_id == {int(kb_id)}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"清理 Milvus 向量失败（不影响数据库删除）：kb={kb_id} - {exc}")
    # 问答缓存也要跟着走，否则已删知识库的答案会长期占着「高频问答」榜首
    try:
        from app.services.qa_cache import forget_kb

        removed = forget_kb(db, kb_id)
        if removed:
            logger.info(f"已清理该知识库的问答缓存：{removed} 条")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"清理问答缓存失败（不影响数据库删除）：kb={kb_id} - {exc}")
    logger.info(f"知识库已删除：id={kb_id}（共享集合 {collection} 中对应向量已清理）")


def refresh_stats(db: Session, kb: KnowledgeBase) -> None:
    """重算文档数/块数。"""
    kb.document_count = int(
        db.scalar(select(func.count(Document.id)).where(Document.knowledge_base_id == kb.id)) or 0
    )
    kb.chunk_count = int(
        db.scalar(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.knowledge_base_id == kb.id)
        )
        or 0
    )
    db.flush()
