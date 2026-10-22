"""文档与文档块接口。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.exceptions import BizError
from app.db.session import get_db
from app.models.document import Document, DocumentChunk
from app.models.user import User
from app.schemas.common import ok, page
from app.schemas.document import ChunkOut, ChunkUpdate, DocumentDetail, DocumentOut
from app.services import document_service, knowledge_service

router = APIRouter(tags=["文档"])


def _get_owned_document(db: Session, document_id: int, user_id: int) -> Document:
    """写操作用：只能动自己的文档。"""
    document = db.get(Document, document_id)
    if document is None or document.user_id != user_id:
        raise BizError("文档不存在或无权访问", status_code=404)
    return document


def _get_readable_document(db: Session, document_id: int, user_id: int) -> Document:
    """读操作用：共享模式下全院可见，写操作仍走 `_get_owned_document`。"""
    document = db.get(Document, document_id)
    if document is None:
        raise BizError("文档不存在", status_code=404)
    if not settings.kb_shared_read and document.user_id != user_id:
        raise BizError("文档不存在或无权访问", status_code=404)
    return document


def _get_owned_chunk(db: Session, chunk_id: int, user_id: int) -> DocumentChunk:
    chunk = db.get(DocumentChunk, chunk_id)
    if chunk is None:
        raise BizError("文档块不存在", status_code=404)
    document = db.get(Document, chunk.document_id)
    if document is None or document.user_id != user_id:
        raise BizError("文档块不存在或无权访问", status_code=404)
    return chunk


@router.get("/knowledge-bases/{kb_id}/documents", summary="知识库下的文档列表")
def list_documents(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    knowledge_service.get_readable_knowledge_base(db, kb_id, current_user.id)
    rows = list(
        db.scalars(
            select(Document)
            .where(Document.knowledge_base_id == kb_id)
            .order_by(Document.created_at.desc())
        )
    )
    return ok([DocumentOut.model_validate(item).model_dump(mode="json") for item in rows])


@router.post("/knowledge-bases/{kb_id}/documents", summary="上传文档并解析入库")
def upload_document(
    kb_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="离线文档"),
    chunk_size: int = Form(default=500, ge=100, le=4000),
    chunk_overlap: int = Form(default=100, ge=0, le=1000),
    retrieval_mode: str = Form(default="hybrid", pattern="^(dense|hybrid)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    kb = knowledge_service.get_knowledge_base(db, kb_id, current_user.id)
    content = file.file.read()
    document = document_service.create_document(
        db=db,
        kb=kb,
        user_id=current_user.id,
        filename=file.filename or "未命名文件",
        content=content,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        retrieval_mode=retrieval_mode,
    )
    db.commit()
    # 解析入库放到后台，接口立即返回，前端轮询状态
    background_tasks.add_task(document_service.ingest_document, document.id)
    return ok(DocumentOut.model_validate(document).model_dump(mode="json"), message="文件已上传，正在解析")


@router.get("/documents/{document_id}", summary="文档详情")
def get_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = _get_readable_document(db, document_id, current_user.id)
    kb = knowledge_service.get_readable_knowledge_base(db, document.knowledge_base_id, current_user.id)
    detail = DocumentDetail.model_validate(document)
    detail.knowledge_base_name = kb.name
    return ok(detail.model_dump(mode="json"))


@router.delete("/documents/{document_id}", summary="删除文档")
def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = _get_owned_document(db, document_id, current_user.id)
    document_service.delete_document(db, document)
    return ok(message="文档已删除")


@router.post("/documents/{document_id}/reindex", summary="重新解析文档")
def reindex_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = _get_owned_document(db, document_id, current_user.id)
    kb = knowledge_service.get_knowledge_base(db, document.knowledge_base_id, current_user.id)
    document_service.reindex_document(db, document, kb)
    return ok(DocumentOut.model_validate(document).model_dump(mode="json"), message="重新解析完成")


@router.get("/documents/{document_id}/chunks", summary="文档块列表")
def list_chunks(
    document_id: int,
    page_num: int = Query(default=1, ge=1, alias="page"),
    page_size: int = Query(default=10, ge=1, le=100),
    keyword: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _get_readable_document(db, document_id, current_user.id)
    items, total = document_service.list_chunks(db, document_id, page_num, page_size, keyword)
    return ok(
        page(
            [ChunkOut.model_validate(item).model_dump(mode="json") for item in items],
            total,
            page_num,
            page_size,
        )
    )


@router.patch("/chunks/{chunk_id}", summary="编辑文档块")
def update_chunk(
    chunk_id: int,
    payload: ChunkUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    chunk = _get_owned_chunk(db, chunk_id, current_user.id)
    updated = document_service.update_chunk(db, chunk, payload.content.strip())
    return ok(ChunkOut.model_validate(updated).model_dump(mode="json"), message="保存成功")


@router.delete("/chunks/{chunk_id}", summary="删除文档块")
def delete_chunk(
    chunk_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    chunk = _get_owned_chunk(db, chunk_id, current_user.id)
    document_service.delete_chunk(db, chunk)
    return ok(message="文档块已删除")
