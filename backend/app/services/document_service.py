"""文档服务：上传落盘、解析、切块、向量化、入库，以及块级维护。"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BizError
from app.db.session import SessionLocal
from app.models.document import Document, DocumentChunk
from app.models.knowledge import KnowledgeBase
from app.services.chunking import split_blocks
from app.services.embedding import get_embedder
from app.services.knowledge_service import refresh_stats
from app.services.parsing import get_file_type, is_supported, parse_file
from app.services.vector_store import get_vector_store

def _image_payload(chunk: DocumentChunk) -> list[dict]:
    """把块上的图片序列化成动态字段内容（规范 URL，不含签名）。

    这部分只给前端/调试看，检索时仍以 MySQL 为准；签名在输出时现算。
    """
    raw = (chunk.image_urls or "").strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    payload: list[dict] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        payload.append(
            {
                "url": item["url"],
                "caption": item.get("caption") or "",
                "kind": item.get("kind") or "figure",
            }
        )
    return payload


_ALLOWED_SUFFIX = {
    ".pdf",
    ".pptx",
    ".docx",
    ".md",
    ".markdown",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp",
}

# 多个文档同时解析会争抢 knowledge_bases / documents 的行锁并触发 MySQL 死锁，
# 且向量化本身是 CPU 密集型任务，这里统一串行执行。
_INGEST_LOCK = threading.Lock()


def save_upload(knowledge_base_id: int, filename: str, content: bytes) -> Path:
    """保存上传文件到本地磁盘。"""
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise BizError(f"不支持的文件类型：{suffix or '未知'}，支持 PDF/PPT/Word/Markdown/图片")
    if not content:
        raise BizError("上传文件内容为空")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise BizError(f"文件超过 {settings.max_upload_mb}MB 限制")

    target_dir = settings.upload_path / f"kb_{knowledge_base_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = target_dir / f"{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(content)
    return stored


def create_document(
    db: Session,
    kb: KnowledgeBase,
    user_id: int,
    filename: str,
    content: bytes,
    chunk_size: int,
    chunk_overlap: int,
    retrieval_mode: str,
) -> Document:
    """创建文档记录（解析在后台进行）。"""
    if not is_supported(filename):
        raise BizError(f"不支持的文件类型：{Path(filename).suffix}")
    if chunk_overlap >= chunk_size:
        raise BizError("重叠大小必须小于切块大小")

    store = get_vector_store()
    # 检索方式在首次解析时确定，避免同一知识库内模式不一致；
    # 集合由所有知识库共用，任何情况下都不重建、不清空
    if kb.chunk_count == 0 and retrieval_mode != kb.retrieval_mode:
        kb.retrieval_mode = retrieval_mode
        kb.chunk_size = chunk_size
        kb.chunk_overlap = chunk_overlap
    elif retrieval_mode != kb.retrieval_mode:
        raise BizError(
            f"该知识库已按「{'混合检索' if kb.retrieval_mode == 'hybrid' else '稠密检索'}」建库，"
            "不能更改检索方式，请新建知识库"
        )
    store.ensure_collection(store.collection_name(), kb.retrieval_mode)

    stored_path = save_upload(kb.id, filename, content)
    document = Document(
        knowledge_base_id=kb.id,
        user_id=user_id,
        filename=filename,
        stored_path=str(stored_path),
        file_type=get_file_type(filename),
        file_size=len(content),
        status="pending",
    )
    db.add(document)
    db.flush()
    refresh_stats(db, kb)
    logger.info(f"文档已上传：id={document.id} name={filename} kb={kb.id}")
    return document


def ingest_document(document_id: int) -> None:
    """解析 -> 切块 -> 向量化 -> 写入 Milvus（独立事务，供后台任务调用）。

    解析任务串行执行，避免并发写入同一知识库导致的死锁。
    """
    with _INGEST_LOCK:
        _ingest_with_retry(document_id)


def _ingest_with_retry(document_id: int, retries: int = 2) -> None:
    for attempt in range(retries + 1):
        db = SessionLocal()
        try:
            document = db.get(Document, document_id)
            if document is None:
                logger.warning(f"待解析文档不存在：{document_id}")
                return
            kb = db.get(KnowledgeBase, document.knowledge_base_id)
            if kb is None:
                return

            document.status = "processing"
            document.error_message = ""
            db.commit()

            try:
                _run_pipeline(db, document, kb)
                document.status = "completed"
                db.commit()
                logger.info(f"文档解析完成：id={document.id} 块数={document.chunk_count}")
                return
            except OperationalError as exc:
                db.rollback()
                if "Deadlock" in str(exc) and attempt < retries:
                    logger.warning(f"数据库死锁，第 {attempt + 1} 次重试解析：doc={document_id}")
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                failed = db.get(Document, document_id)
                if failed is not None:
                    failed.status = "failed"
                    failed.error_message = str(exc)[:1000]
                    db.commit()
                logger.exception(f"文档解析失败：id={document_id} - {exc}")
                return
        finally:
            db.close()


def _run_pipeline(db: Session, document: Document, kb: KnowledgeBase) -> None:
    """执行完整解析流程，成功后更新文档统计。"""
    store = get_vector_store()
    collection = store.collection_name()
    # 清理旧数据，支持重复解析
    _clear_document_vectors(document.id, collection)
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    db.flush()

    blocks = parse_file(document.stored_path, document.filename, document_id=document.id)
    pieces = split_blocks(blocks, kb.chunk_size, kb.chunk_overlap, document_id=document.id)
    if not pieces:
        raise BizError("文档解析后没有任何有效文本块")

    # 先落库拿到 chunk_id（父块与图片一并写入，供图文问答使用）
    chunk_rows: list[DocumentChunk] = []
    for index, piece in enumerate(pieces):
        chunk = DocumentChunk(
            document_id=document.id,
            knowledge_base_id=kb.id,
            chunk_index=index,
            page=int(piece.get("page") or -1),
            content=piece["content"],
            parent_id=int(piece.get("parent_id") or 0),
            parent_content=piece.get("parent_content") or piece["content"],
            image_urls=json.dumps(piece.get("images") or [], ensure_ascii=False),
            char_count=piece["char_count"],
        )
        db.add(chunk)
        chunk_rows.append(chunk)
    db.flush()

    embedder = get_embedder()
    store.ensure_collection(collection, kb.retrieval_mode)

    batch_size = max(1, settings.embedding_batch_size)
    for start in range(0, len(chunk_rows), batch_size):
        batch = chunk_rows[start : start + batch_size]
        dense_vectors, sparse_vectors = embedder.encode([item.content for item in batch])
        rows = []
        for chunk, dense, sparse in zip(batch, dense_vectors, sparse_vectors):
            row = {
                "kb_id": kb.id,
                "document_id": document.id,
                "chunk_id": chunk.id,
                "page": chunk.page,
                "text": chunk.content,
                "dense": dense,
                # 共享集合统一带稀疏字段，写入时总是写，检索时按知识库模式决定是否用
                "sparse": sparse,
                # 动态字段：图片地址 + 父块 ID/父块全文随实体一起写入，
                # 这样在 Milvus 里能直接看到「这条向量属于哪个父块、父块长什么样」
                "images": _image_payload(chunk),
                "parent_id": int(chunk.parent_id or 0),
                "parent_content": chunk.parent_content or chunk.content,
            }
            rows.append(row)
        ids = store.insert(collection, rows)
        for chunk, milvus_id in zip(batch, ids):
            chunk.milvus_id = milvus_id

    document.chunk_count = len(chunk_rows)
    document.char_count = sum(item.char_count for item in chunk_rows)
    kb.chunk_size = kb.chunk_size or settings.rag_chunk_size
    db.flush()
    refresh_stats(db, kb)
    logger.info(
        f"文档入库完成：doc={document.id} 块数={document.chunk_count} 字符={document.char_count} "
        f"mode={kb.retrieval_mode}"
    )


def _clear_document_vectors(document_id: int, collection: str) -> None:
    store = get_vector_store()
    if store.has_collection(collection):
        try:
            store.delete_by_filter(collection, f"document_id == {int(document_id)}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"清理文档向量失败：doc={document_id} - {exc}")


def delete_document(db: Session, document: Document) -> None:
    """删除文档及其向量。"""
    kb = db.get(KnowledgeBase, document.knowledge_base_id)
    _clear_document_vectors(document.id, get_vector_store().collection_name())
    db.delete(document)
    db.flush()
    if kb is not None:
        refresh_stats(db, kb)
    stored = Path(document.stored_path)
    if stored.exists():
        try:
            stored.unlink()
        except OSError:
            logger.warning(f"删除本地文件失败：{stored}")
    logger.info(f"文档已删除：id={document.id}")


def reindex_document(db: Session, document: Document, kb: KnowledgeBase) -> None:
    """重新解析文档（同步执行）。"""
    document.status = "processing"
    db.flush()
    _run_pipeline(db, document, kb)
    document.status = "completed"
    db.flush()


def list_chunks(
    db: Session, document_id: int, page: int = 1, page_size: int = 10, keyword: str | None = None
) -> tuple[list[DocumentChunk], int]:
    stmt = select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    count_stmt = select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
    if keyword:
        stmt = stmt.where(DocumentChunk.content.like(f"%{keyword.strip()}%"))
        count_stmt = count_stmt.where(DocumentChunk.content.like(f"%{keyword.strip()}%"))
    total = int(db.scalar(count_stmt) or 0)
    items = list(
        db.scalars(
            stmt.order_by(DocumentChunk.chunk_index)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return items, total


def update_chunk(db: Session, chunk: DocumentChunk, content: str) -> DocumentChunk:
    """编辑块内容：同步更新向量库。"""
    kb = db.get(KnowledgeBase, chunk.knowledge_base_id)
    store = get_vector_store()
    collection = store.collection_name()

    embedder = get_embedder()
    dense_vectors, sparse_vectors = embedder.encode([content])
    row = {
        "kb_id": chunk.knowledge_base_id,
        "document_id": chunk.document_id,
        "chunk_id": chunk.id,
        "page": chunk.page,
        "text": content,
        "dense": dense_vectors[0],
        # 共享集合的 sparse 字段始终写入
        "sparse": sparse_vectors[0],
        "images": _image_payload(chunk),
        "parent_id": int(chunk.parent_id or 0),
        "parent_content": chunk.parent_content or content,
    }

    # 先删旧向量再插入新向量（Milvus 主键为自增，无法原地更新）
    store.delete_by_filter(collection, f"chunk_id == {int(chunk.id)}")
    ids = store.insert(collection, [row])
    chunk.content = content
    chunk.char_count = len(content)
    chunk.milvus_id = ids[0] if ids else None
    db.flush()

    document = db.get(Document, chunk.document_id)
    if document is not None:
        total = db.scalar(
            select(func.sum(DocumentChunk.char_count)).where(
                DocumentChunk.document_id == document.id
            )
        )
        document.char_count = int(total or 0)
    logger.info(f"文档块已更新：chunk={chunk.id}")
    return chunk


def delete_chunk(db: Session, chunk: DocumentChunk) -> None:
    """删除单个块。"""
    kb = db.get(KnowledgeBase, chunk.knowledge_base_id)
    store = get_vector_store()
    if kb is not None:
        store.delete_by_filter(store.collection_name(), f"chunk_id == {int(chunk.id)}")
    document_id = chunk.document_id
    db.delete(chunk)
    db.flush()

    document = db.get(Document, document_id)
    if document is not None:
        remaining = int(
            db.scalar(
                select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
            )
            or 0
        )
        document.chunk_count = remaining
        total = db.scalar(
            select(func.sum(DocumentChunk.char_count)).where(DocumentChunk.document_id == document_id)
        )
        document.char_count = int(total or 0)
    if kb is not None:
        refresh_stats(db, kb)
    logger.info(f"文档块已删除：chunk={chunk.id}")
