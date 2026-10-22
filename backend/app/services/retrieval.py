"""检索服务：多路 query 召回 → RRF 融合 → 回填父块 → 父块去重 → 精排 → topK。

对应流程图右半部分的检索主干：

    query 变体（直接/简化/回溯/子问题/假设答案）
        → 稠密+稀疏双路召回（共享集合内按 kb_id 过滤）
        → RRF 融合
        → 回填父块（优先 MySQL，退回 Milvus 动态字段）
        → 按父块去重
        → bge-reranker 精排（query × 父块，与流程图一致）
        → topK 上下文
"""
from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document, DocumentChunk
from app.models.knowledge import KnowledgeBase
from app.services.embedding import get_embedder
from app.services.media import resolve_url
from app.services.vector_store import get_vector_store

# 父块中的图片标记：[关联图片: 图 1 说明 / 图片链接: http://...]
_IMAGE_MARKER = re.compile(r"\[关联图片[:：]\s*(.*?)\s*/\s*图片链接[:：]\s*(\S+?)\]")


def extract_images(parent_content: str) -> list[dict]:
    """从父块里提取 [关联图片 / 图片链接] 标记。"""
    if not parent_content:
        return []
    images: list[dict] = []
    seen: set[str] = set()
    for caption, url in _IMAGE_MARKER.findall(parent_content):
        if url in seen:
            continue
        seen.add(url)
        images.append({"caption": caption.strip(), "url": url.strip(), "kind": "figure"})
    return images


def _images_of(chunk: DocumentChunk) -> list[dict]:
    """优先用结构化字段，回退到父块标记（兼容只写了标记的老数据）。

    库里存的是规范 URL（域名 + 对象键），这里统一过一遍 `resolve_url`：
    私有空间按需签名，保证每次调用拿到的都是当前可访问的地址。
    """
    items = _stored_images_of(chunk)
    resolved: list[dict] = []
    for item in items:
        url = resolve_url(item.get("url", ""))
        if not url:
            continue
        resolved.append({**item, "url": url})
    return resolved


def _stored_images_of(chunk: DocumentChunk) -> list[dict]:
    raw = (chunk.image_urls or "").strip()
    if raw:
        try:
            items = json.loads(raw)
            if isinstance(items, list):
                return [
                    {
                        "caption": (item.get("caption") or "示意图").strip(),
                        "url": item.get("url", ""),
                        "kind": item.get("kind") or "figure",
                    }
                    for item in items
                    if isinstance(item, dict) and item.get("url")
                ]
        except json.JSONDecodeError:
            logger.warning(f"图片字段解析失败：chunk={chunk.id}")
    return extract_images(chunk.parent_content or "")


def rrf_fuse(groups: list[list[dict]], k: int | None = None) -> list[dict]:
    """把多路召回结果按 RRF 融合成一路。

    每路内部是已排序的召回列表；同一块在多路出现时累加 1/(k+rank)，
    因此「多路都排前面」的块会被顶上来。
    """
    k = k or settings.rag_rrf_k
    fused: dict[int, dict] = {}
    for group in groups:
        for rank, hit in enumerate(group, start=1):
            chunk_id = int(hit["chunk_id"])
            entry = fused.get(chunk_id)
            if entry is None:
                entry = {
                    "chunk_id": chunk_id,
                    "document_id": int(hit.get("document_id", 0)),
                    "page": int(hit.get("page", -1)),
                    "content": hit.get("content", ""),
                    "parent_id": int(hit.get("parent_id") or 0),
                    "parent_content": hit.get("parent_content") or "",
                    "rrf": 0.0,
                    "best_score": 0.0,
                    "labels": [],
                    "hits": 0,
                }
                fused[chunk_id] = entry
            entry["rrf"] += 1.0 / (k + rank)
            entry["hits"] += 1
            entry["best_score"] = max(entry["best_score"], float(hit.get("score", 0.0) or 0.0))
            label = hit.get("label")
            if label and label not in entry["labels"]:
                entry["labels"].append(label)
    return sorted(fused.values(), key=lambda item: item["rrf"], reverse=True)


def dedupe_by_parent(items: list[dict]) -> list[dict]:
    """按父块去重：同一父块只保留最高分子块，其余记为兄弟块。

    父块是「整页原文」（md/Word 等无页码文档是整篇/整段），同页多个 chunk 命中时
    应合并成一条参考资料，否则 top_k 会被同一页的碎片占满。
    """
    kept: dict[Any, dict] = {}
    for item in items:
        parent_id = int(item.get("parent_id") or 0)
        if parent_id:
            key = ("p", parent_id)
        elif (item.get("page") or -1) > 0:
            key = ("dp", item["document_id"], item["page"])
        else:
            key = ("c", item["chunk_id"])
        current = kept.get(key)
        if current is None:
            item["siblings"] = 0
            kept[key] = item
        else:
            current["siblings"] += 1
            if item["rrf"] > current["rrf"]:
                item["siblings"] = current["siblings"]
                kept[key] = item
    return sorted(kept.values(), key=lambda item: item["rrf"], reverse=True)


def retrieve_multi(
    db: Session,
    queries: list[dict],
    kb_ids: list[int],
    user_id: int,
    top_k: int | None = None,
    candidate_k: int | None = None,
    use_rerank: bool | None = None,
) -> list[dict]:
    """多路召回 + 融合 + 去重 + 精排。

    queries: [{"text": "...", "label": "direct|simplified|sub|backtrack|hyde"}]
    """
    queries = [item for item in queries if (item.get("text") or "").strip()]
    if not queries or not kb_ids:
        return []

    top_k = top_k or settings.rag_top_k
    candidate_k = candidate_k or max(settings.rag_candidate_k, top_k)
    use_rerank = settings.rerank_enabled if use_rerank is None else use_rerank

    # 共享模式下不限定所有者：同事选中的库也要能检索到
    kb_stmt = select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids))
    if not settings.kb_shared_read:
        kb_stmt = kb_stmt.where(KnowledgeBase.user_id == user_id)
    kbs = list(db.scalars(kb_stmt))
    if not kbs:
        logger.warning(f"未找到可检索的知识库：{kb_ids}")
        return []

    store = get_vector_store()
    collection = store.collection_name()
    selected_ids = [kb.id for kb in kbs]
    retrieval_mode = "hybrid" if any(kb.retrieval_mode == "hybrid" for kb in kbs) else "dense"

    # 一次前向编码所有变体，避免 N 次模型调用
    embedder = get_embedder()
    texts = [item["text"] for item in queries]
    dense_vectors, sparse_vectors = embedder.encode(texts)

    groups: list[list[dict]] = []
    for index, item in enumerate(queries):
        hits = store.search(
            name=collection,
            dense_vector=dense_vectors[index],
            sparse_vector=sparse_vectors[index] if retrieval_mode == "hybrid" else None,
            retrieval_mode=retrieval_mode,
            limit=candidate_k,
            kb_ids=selected_ids,
        )
        for hit in hits:
            hit["label"] = item.get("label", "direct")
        groups.append(hits)
        logger.info(f"召回[{item.get('label')}] {len(hits)} 条 —— {item['text'][:32]}")

    fused = rrf_fuse(groups)
    if not fused:
        return []

    # 回填父块：MySQL 是权威来源（chunk.parent_id / parent_content），
    # 拿不到时退回 Milvus 动态字段里的副本（旧数据、或文档刚被删）
    rows = db.execute(
        select(DocumentChunk, Document, KnowledgeBase)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(KnowledgeBase, KnowledgeBase.id == DocumentChunk.knowledge_base_id)
        .where(DocumentChunk.id.in_([item["chunk_id"] for item in fused]))
    ).all()
    rows_by_chunk = {chunk.id: (chunk, document, kb) for chunk, document, kb in rows}
    for item in fused:
        chunk = rows_by_chunk.get(item["chunk_id"], (None, None, None))[0]
        if chunk is not None:
            item["parent_id"] = int(chunk.parent_id or 0) or item.get("parent_id", 0)
            item["parent_content"] = chunk.parent_content or item["content"]
        else:
            item["parent_content"] = item.get("parent_content") or item["content"]

    # 父块去重：同一个父块只留最高分子块
    fused = dedupe_by_parent(fused)

    # 精排用的是「原始问题」和「父块全文」，与流程图第 6 步一致
    query = texts[0]
    pool = fused[:candidate_k]
    if use_rerank and len(pool) > 1:
        try:
            from app.services.reranker import get_reranker

            scores = get_reranker().score(query, [item["parent_content"] for item in pool])
            for item, score in zip(pool, scores):
                item["rerank_score"] = float(score)
            pool.sort(key=lambda item: item["rerank_score"], reverse=True)
            logger.info(f"精排完成（query × 父块）：候选={len(pool)}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"重排失败，回退到 RRF 分数：{exc}")

    # 稠密余弦用于「是否真有依据」的判定，与检索模式无关
    try:
        relevance = store.max_dense_score(collection, dense_vectors[0], kb_ids=selected_ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"相关度计算失败：{exc}")
        relevance = 0.0

    candidates = pool[:top_k]
    results: list[dict] = []
    for item in candidates:
        chunk, document, kb = rows_by_chunk.get(item["chunk_id"], (None, None, None))
        parent_content = item.get("parent_content") or item["content"]
        images = _images_of(chunk) if chunk is not None else []
        if chunk is not None and not images:
            images = extract_images(parent_content)
        results.append(
            {
                "chunk_id": item["chunk_id"],
                "document_id": item["document_id"],
                "document_name": document.filename if document else "未知文档",
                "knowledge_base_id": kb.id if kb else 0,
                "knowledge_base_name": kb.name if kb else "未知知识库",
                "content": item["content"],
                "parent_id": int(item.get("parent_id") or 0),
                "parent_content": parent_content,
                "page": item.get("page", -1),
                "score": round(float(item.get("rerank_score", item.get("rrf", 0.0))), 6),
                "relevance": round(relevance, 4),
                "images": images,
                "has_image": bool(images),
                "variants": item.get("labels", []),
                "siblings": int(item.get("siblings", 0)),
            }
        )
    logger.info(
        f"命中 {len(results)} 条（融合前 {sum(len(g) for g in groups)} 条，"
        f"去重后 {len(fused)} 条），带图 {sum(1 for r in results if r['has_image'])} 条"
    )
    return results


def retrieve(
    db: Session,
    query: str,
    kb_ids: list[int],
    user_id: int,
    top_k: int | None = None,
    candidate_k: int | None = None,
    use_rerank: bool | None = None,
) -> list[dict]:
    """单 query 检索（兼容旧调用）。"""
    return retrieve_multi(
        db,
        [{"text": query, "label": "direct"}],
        kb_ids=kb_ids,
        user_id=user_id,
        top_k=top_k,
        candidate_k=candidate_k,
        use_rerank=use_rerank,
    )
