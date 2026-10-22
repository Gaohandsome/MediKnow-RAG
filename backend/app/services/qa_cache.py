"""高频问答缓存：MySQL 存 300 条热问题，Redis 做一级命中，BM25 做近似判定。

三级判定（对应流程图的左半部分）：

    用户 query
      ├─ ① 归一化后命中 Redis `qa:q`（一次 HGET，O(1)）→ 直接回放答案，零模型调用
      ├─ ② 否则取 Redis 里的 `qa:index`（问题 + 分词），算 BM25 对称覆盖率
      │     ├─ ≥ QA_CACHE_THRESHOLD → 回放 MySQL 里对应答案（等价于「换个问法问过」）
      │     └─ < 阈值 → 交给 RAG 检索
      └─ ③ RAG 回答完 → 沉淀回 MySQL，并让 Redis 索引失效，下次重建

存储分工：
- **MySQL `qa_pairs`**：真值 + 持久化，只保留 hit_count 最高的 `QA_CACHE_MAX_PAIRS` 条（默认 300）；
- **Redis `qa:q`（hash）**：归一化问题 → 答案/引用快照，精确命中的快路径；
- **Redis `qa:index`（string）**：BM25 语料（含分词），Redis 缺失时才从 MySQL 重建并回写；
- **Redis `qa:hits`（hash）**：命中次数增量，攒够次数批量回写 MySQL，避免每次命中都写库。
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.qa import QAPair
from app.services.bm25 import BM25, tokenize
from app.services.cache import get_json, get_kv, set_json

_INDEX_KEY = "qa:index"      # 全量索引 JSON（BM25 语料）
_EXACT_KEY = "qa:q"          # hash：归一化问题 → 条目 JSON（精确命中）
_HITS_KEY = "qa:hits"        # hash：归一化问题 → 待回写的命中次数
_PENDING_KEY = "qa:hits:n"   # string：待回写次数，攒够就 flush
_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize(question: str) -> str:
    """问题归一化：全角转半角、小写、去标点空白。用于精确命中。"""
    text = unicodedata.normalize("NFKC", question or "").strip().lower()
    return _PUNCT_RE.sub("", text)


def _strip_signature(url: str) -> str:
    """去掉图片 URL 上的签名参数，落库后不会过期。"""
    return (url or "").split("?")[0]


def _sanitize_contexts(contexts: list[dict]) -> list[dict]:
    """缓存里只保留可长期复用的字段（签名 URL 必须去掉）。"""
    cleaned: list[dict] = []
    for item in contexts or []:
        images = [
            {**image, "url": _strip_signature(image.get("url", ""))}
            for image in item.get("images") or []
            if isinstance(image, dict)
        ]
        cleaned.append(
            {
                "chunk_id": item.get("chunk_id"),
                "document_id": item.get("document_id"),
                "document_name": item.get("document_name"),
                "knowledge_base_id": item.get("knowledge_base_id"),
                "knowledge_base_name": item.get("knowledge_base_name"),
                "content": item.get("content"),
                "parent_content": item.get("parent_content"),
                "page": item.get("page"),
                "score": item.get("score"),
                "images": images,
                "has_image": bool(images),
            }
        )
    return cleaned


def _entry(row: QAPair) -> dict[str, Any]:
    """MySQL 行 → 索引条目（tokens 是 BM25 的语料，不重复存进 hash）。"""
    return {
        "key": row.question_key,
        "question": row.question,
        "tokens": tokenize(row.question),
        "answer": row.answer,
        "kb_ids": list(row.kb_ids or []),
        "hit_count": row.hit_count,
        "contexts": row.contexts or [],
        "plan": row.plan or {},
    }


def _replay_payload(item: dict[str, Any]) -> dict[str, Any]:
    """精确命中要回放的字段（去掉 tokens，省 Redis 内存）。"""
    return {
        "question": item["question"],
        "answer": item["answer"],
        "kb_ids": item.get("kb_ids") or [],
        "contexts": item.get("contexts") or [],
        "plan": item.get("plan") or {},
    }


def _publish(index: list[dict[str, Any]]) -> None:
    """把索引同时写进 `qa:index`（BM25 用）和 `qa:q`（精确命中用）。"""
    kv = get_kv()
    ttl = int(settings.qa_cache_ttl or 0)
    set_json(_INDEX_KEY, index, ttl)
    # 先清空再整批写，避免问题被改写后 hash 里残留旧条目
    kv.delete(_EXACT_KEY)
    kv.hset_map(
        _EXACT_KEY,
        {
            item["key"]: json.dumps(_replay_payload(item), ensure_ascii=False)
            for item in index
        },
        ttl,
    )


def _invalidate() -> None:
    """数据变更：两个 key 一起失效，下次查询重建。"""
    kv = get_kv()
    kv.delete(_INDEX_KEY)
    kv.delete(_EXACT_KEY)


def _load_index(db: Session, force: bool = False) -> list[dict[str, Any]]:
    """取问答索引：Redis 优先，缺失则从 MySQL 重建并回写。"""
    if not force:
        cached = get_json(_INDEX_KEY)
        if isinstance(cached, list):
            return cached

    rows = list(
        db.scalars(
            select(QAPair)
            .order_by(QAPair.hit_count.desc(), QAPair.updated_at.desc())
            .limit(settings.qa_cache_max_pairs)
        )
    )
    index = [_entry(row) for row in rows]
    _publish(index)
    logger.info(f"问答索引已重建：{len(index)} 条（写入 {get_kv().backend}）")
    return index


def _exact_lookup(key: str, selected: set[int]) -> dict[str, Any] | None:
    """① 精确命中：一次 HGET，不解析全量索引。"""
    raw = get_kv().hget(_EXACT_KEY, key)
    if not raw:
        return None
    try:
        item = json.loads(raw)
    except json.JSONDecodeError:
        return None
    kb_of_item = {int(item) for item in (item.get("kb_ids") or [])}
    if selected and not (kb_of_item & selected):
        return None
    return {
        "question": item.get("question") or key,
        "answer": item.get("answer") or "",
        "contexts": item.get("contexts") or [],
        "plan": item.get("plan") or {},
        "score": 1.0,
        "source": "exact",
    }


def lookup(db: Session, question: str, kb_ids: list[int]) -> dict[str, Any] | None:
    """查缓存。返回 {answer, contexts, score, source, question} 或 None。"""
    if not settings.qa_cache_enabled or not question.strip():
        return None

    key = normalize(question)
    if not key:
        return None
    selected = {int(item) for item in (kb_ids or [])}

    # ① 问过一模一样的问题：Redis hash 一次命中，连索引都不用碰
    try:
        hit = _exact_lookup(key, selected)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"精确缓存查询失败，继续走 BM25：{exc}")
        hit = None
    if hit is not None:
        return hit

    # ② 问法不同：在索引上算 BM25 对称覆盖率
    try:
        index = _load_index(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"问答索引加载失败，跳过缓存：{exc}")
        return None

    candidates = [
        entry
        for entry in index
        if not selected or (set(entry.get("kb_ids") or []) & selected)
    ]
    if not candidates:
        return None

    # 兜底：hash 被 Redis 重启/过期清掉、但索引还在时，仍要能精确命中
    for entry in candidates:
        if entry["key"] == key:
            return {
                "question": entry["question"],
                "answer": entry["answer"],
                "contexts": entry.get("contexts") or [],
                "plan": entry.get("plan") or {},
                "score": 1.0,
                "source": "exact",
            }

    query_tokens = tokenize(question)
    if not query_tokens:
        return None
    corpus = [entry["tokens"] for entry in candidates]
    scores = BM25(corpus).scores(query_tokens)
    best_index = max(range(len(scores)), key=lambda i: scores[i])
    best_score = float(scores[best_index])
    if best_score < settings.qa_cache_threshold:
        return None

    best = candidates[best_index]
    logger.info(f"BM25 命中缓存：score={best_score:.3f} 原问题={best['question']}")
    return {
        "question": best["question"],
        "answer": best["answer"],
        "contexts": best.get("contexts") or [],
        "plan": best.get("plan") or {},
        "score": round(best_score, 4),
        "source": "bm25",
    }


def record(
    db: Session,
    question: str,
    answer: str,
    kb_ids: list[int],
    contexts: list[dict],
    plan: dict | None = None,
) -> None:
    """沉淀一次问答：同问题累加命中次数，答案以最新为准。"""
    if not settings.qa_cache_enabled:
        return
    key = normalize(question)
    if not key or len(answer.strip()) < settings.qa_cache_min_answer_chars:
        return

    payload = _sanitize_contexts(contexts)
    existing = db.scalar(select(QAPair).where(QAPair.question_key == key))
    created = existing is None
    if created:
        db.add(
            QAPair(
                question=question.strip()[:500],
                question_key=key,
                answer=answer.strip(),
                kb_ids=list(kb_ids or []),
                contexts=payload,
                plan=plan or {},
                hit_count=1,
            )
        )
    else:
        existing.hit_count += 1
        existing.answer = answer.strip()
        existing.kb_ids = list(kb_ids or [])
        existing.contexts = payload
        existing.plan = plan or existing.plan
    db.commit()
    # 只留高频的那么多条，超了就按命中数淘汰（刚进来的这条保底留下）
    if created:
        prune(db, protect={key})
    # 索引失效，下次查询重建（避免多进程各自维护增量）
    _invalidate()


def prune(db: Session, cap: int | None = None, protect: set[str] | None = None) -> int:
    """MySQL 只保留 hit_count 最高的 cap 条，超出的低频问答直接删。

    `protect` 里的问题不参与淘汰——刚沉淀进来的新问题如果一进来就被删掉，
    下次同样的提问又要重新跑一遍 RAG，等于缓存永远热不起来。
    """
    limit = int(cap or settings.qa_cache_max_pairs)
    total = int(db.scalar(select(func.count()).select_from(QAPair)) or 0)
    if total <= limit:
        return 0
    keep: list[int] = []
    protected: list[int] = []
    rows = db.scalars(
        select(QAPair).order_by(QAPair.hit_count.desc(), QAPair.updated_at.desc())
    )
    guarded = protect or set()
    for row in rows:
        if row.question_key in guarded:
            protected.append(row.id)
        else:
            keep.append(row.id)
    ordered = (protected + keep)[:limit]
    removed = db.execute(delete(QAPair).where(QAPair.id.notin_(ordered))).rowcount or 0
    db.commit()
    logger.info(f"问答缓存超过上限（{total} > {limit}），淘汰 {removed} 条低频问答")
    return removed


def flush_hits(db: Session) -> int:
    """把 Redis 里攒的命中次数批量回写 MySQL。"""
    kv = get_kv()
    pending = kv.hgetall(_HITS_KEY)
    if not pending:
        kv.delete(_PENDING_KEY)
        return 0

    keys = list(pending)
    rows = list(db.scalars(select(QAPair).where(QAPair.question_key.in_(keys))))
    by_key = {row.question_key: row for row in rows}
    applied = 0
    for key, raw in pending.items():
        try:
            delta = int(raw)
        except (TypeError, ValueError):
            delta = 0
        row = by_key.get(key)
        if delta <= 0 or row is None:
            # 条目已被淘汰：计数没有归属，直接丢弃
            kv.hdel(_HITS_KEY, key)
            continue
        row.hit_count = int(row.hit_count or 0) + delta
        # 减掉已回写的量再删，避免和并发 INCR 抢跑丢计数
        if kv.hincrby(_HITS_KEY, key, -delta) <= 0:
            kv.hdel(_HITS_KEY, key)
        applied += 1
    db.commit()
    kv.delete(_PENDING_KEY)
    if applied:
        logger.info(f"命中计数回写 MySQL：{applied} 条")
    return applied


def forget_kb(db: Session, kb_id: int) -> int:
    """知识库删除后清理它的问答缓存。

    只属于该库的条目直接删除（否则会长期占着「高频问答」榜首，且再也命中不到）；
    同时也归属于其他库的条目只摘掉这个 kb_id，别把还能用的缓存一起删了。
    """
    target = int(kb_id)
    removed = 0
    changed = False
    for row in db.scalars(select(QAPair)):
        ids = [int(item) for item in (row.kb_ids or [])]
        if target not in ids:
            continue
        rest = [item for item in ids if item != target]
        if rest:
            row.kb_ids = rest
        else:
            db.delete(row)
            removed += 1
        changed = True
    if changed:
        db.commit()
        # 索引要立刻失效，否则下一次查询还会拿旧条目
        _invalidate()
    return removed


def resolve_cached_contexts(contexts: list[dict]) -> list[dict]:
    """缓存里的图片 URL 是无签名的规范地址，回放时重新签名。"""
    from app.services.media import refresh_url

    resolved: list[dict] = []
    for item in contexts or []:
        images = [
            {**image, "url": refresh_url(image.get("url", ""))}
            for image in item.get("images") or []
            if isinstance(image, dict)
        ]
        images = [image for image in images if image.get("url")]
        resolved.append({**item, "images": images, "has_image": bool(images)})
    return resolved


def touch(db: Session, question: str) -> None:
    """缓存命中一次：只在 Redis 累加计数，攒够再批量回写。

    注意**不能**在这里删索引——每命中一次就把索引废掉，下一个请求又要从 MySQL
    重建 300 条并重新分词，等于自己把自己的快路径拆了。
    """
    key = normalize(question)
    if not key:
        return
    try:
        kv = get_kv()
        kv.hincrby(_HITS_KEY, key, 1)
        every = int(settings.qa_hit_flush_every or 0)
        if every > 0 and kv.incr(_PENDING_KEY) >= every:
            flush_hits(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"缓存命中计数失败（不影响回答）：{exc}")


def stats(db: Session) -> dict[str, Any]:
    """缓存规模快照：MySQL 条数 / Redis 索引条数 / 待回写计数。"""
    kv = get_kv()
    try:
        pairs = int(db.scalar(select(func.count()).select_from(QAPair)) or 0)
    except Exception:  # noqa: BLE001
        pairs = -1
    try:
        index_raw = get_json(_INDEX_KEY)
        indexed = len(index_raw) if isinstance(index_raw, list) else 0
        exact_keys = kv.hlen(_EXACT_KEY)
        pending = kv.hgetall(_HITS_KEY)
    except Exception:  # noqa: BLE001
        indexed = exact_keys = -1
        pending = {}
    return {
        "backend": kv.backend,
        "pairs": pairs,
        "max_pairs": settings.qa_cache_max_pairs,
        "indexed": indexed,
        "exact_keys": exact_keys,
        "pending_keys": len(pending),
        "pending_total": sum(int(value) for value in pending.values() if str(value).isdigit()),
        "threshold": settings.qa_cache_threshold,
    }


def hot_questions(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    """统计高频问答对（流程图里「统计高频问答对 → MySQL / Redis」）。"""
    try:
        flush_hits(db)  # 先把 Redis 里攒的计数落库，榜单才是实时的
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"回写命中计数失败：{exc}")
    rows = list(
        db.scalars(select(QAPair).order_by(QAPair.hit_count.desc()).limit(limit))
    )
    return [
        {
            "question": row.question,
            "hit_count": row.hit_count,
            "updated_at": row.updated_at.isoformat(timespec="seconds") if row.updated_at else None,
            "kb_ids": list(row.kb_ids or []),
        }
        for row in rows
    ]
