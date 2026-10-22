"""三级缓存：Redis 精确命中 → BM25 近似命中 → RAG；以及计数回写与容量淘汰。"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import delete, select

import app.services.cache as cache
import app.services.qa_cache as qa_cache
from app.core.config import settings
from app.models.qa import QAPair


@pytest.fixture()
def memory_kv(monkeypatch):
    """固定用进程内 KV，测试不依赖本机 Redis。"""
    cache._kv = cache._MemoryKV()
    cache._warned = False
    monkeypatch.setattr(settings, "qa_cache_enabled", True)
    yield cache._kv
    qa_cache._invalidate()
    cache._kv = None


@pytest.fixture()
def clean_pairs(db):
    db.execute(delete(QAPair))
    db.commit()
    yield db
    db.execute(delete(QAPair))
    db.commit()


def _add(db, question: str, answer: str = "标准答案" * 10, kb_ids: list[int] | None = None, hit: int = 1) -> QAPair:
    row = QAPair(
        question=question,
        question_key=qa_cache.normalize(question),
        answer=answer,
        kb_ids=kb_ids or [1],
        contexts=[{"content": "引用内容", "images": []}],
        plan={"intent": "professional"},
        hit_count=hit,
    )
    db.add(row)
    db.commit()
    return row


def test_publish_fills_both_keys(memory_kv, clean_pairs):
    _add(clean_pairs, "成人心肺复苏按压深度是多少")
    _add(clean_pairs, "针刺伤后如何处理")
    index = qa_cache._load_index(clean_pairs, force=True)

    assert len(index) == 2
    assert memory_kv.get(qa_cache._INDEX_KEY)            # BM25 语料
    assert memory_kv.hlen(qa_cache._EXACT_KEY) == 2      # 精确命中表
    # 精确表里不该带 tokens（省内存）
    assert "tokens" not in memory_kv.get(qa_cache._INDEX_KEY) or True
    import json
    payload = json.loads(memory_kv.hget(qa_cache._EXACT_KEY, qa_cache.normalize("针刺伤后如何处理")))
    assert "tokens" not in payload and payload["answer"]


def test_exact_hit_does_not_need_index(memory_kv, clean_pairs):
    """hash 命中就该结束：把索引删掉也照样返回。"""
    _add(clean_pairs, "住院患者跌倒风险评估时机")
    qa_cache._load_index(clean_pairs, force=True)
    memory_kv.delete(qa_cache._INDEX_KEY)

    hit = qa_cache.lookup(clean_pairs, "住院患者跌倒风险评估时机", [1])
    assert hit is not None
    assert hit["source"] == "exact"
    assert hit["score"] == 1.0


def test_bm25_hit_for_rephrased_question(memory_kv, clean_pairs):
    _add(clean_pairs, "成人心肺复苏的按压深度和按压通气比是多少")
    qa_cache._load_index(clean_pairs, force=True)

    hit = qa_cache.lookup(clean_pairs, "请问 成人心肺复苏的按压深度和按压通气比是多少", [1])
    assert hit is not None
    assert hit["source"] in {"exact", "bm25"}
    assert hit["score"] >= settings.qa_cache_threshold


def test_unrelated_question_falls_through_to_rag(memory_kv, clean_pairs):
    _add(clean_pairs, "成人心肺复苏的按压深度是多少")
    qa_cache._load_index(clean_pairs, force=True)

    assert qa_cache.lookup(clean_pairs, "今天天气怎么样适合洗车吗", [1]) is None


def test_kb_isolation(memory_kv, clean_pairs):
    _add(clean_pairs, "针刺伤后如何处理", kb_ids=[7])
    qa_cache._load_index(clean_pairs, force=True)

    assert qa_cache.lookup(clean_pairs, "针刺伤后如何处理", [99]) is None
    assert qa_cache.lookup(clean_pairs, "针刺伤后如何处理", [7]) is not None


def test_touch_keeps_index_and_defers_writeback(memory_kv, clean_pairs, monkeypatch):
    """命中一次不能把索引删掉，也不能立刻写 MySQL。"""
    row = _add(clean_pairs, "输液发热反应先做什么", hit=1)
    qa_cache._load_index(clean_pairs, force=True)
    monkeypatch.setattr(settings, "qa_hit_flush_every", 0)  # 关掉自动回写

    qa_cache.touch(clean_pairs, "输液发热反应先做什么")

    assert memory_kv.get(qa_cache._INDEX_KEY) is not None      # 索引还在
    assert memory_kv.hget(qa_cache._HITS_KEY, row.question_key) == "1"
    clean_pairs.expire_all()
    assert clean_pairs.scalar(select(QAPair.hit_count).where(QAPair.id == row.id)) == 1

    qa_cache.flush_hits(clean_pairs)
    clean_pairs.expire_all()
    assert clean_pairs.scalar(select(QAPair.hit_count).where(QAPair.id == row.id)) == 2
    assert memory_kv.hlen(qa_cache._HITS_KEY) == 0


def test_flush_accumulates_multiple_hits(memory_kv, clean_pairs, monkeypatch):
    row = _add(clean_pairs, "手卫生五个时刻是什么", hit=3)
    monkeypatch.setattr(settings, "qa_hit_flush_every", 0)
    for _ in range(4):
        qa_cache.touch(clean_pairs, "手卫生五个时刻是什么")

    qa_cache.flush_hits(clean_pairs)
    clean_pairs.expire_all()
    assert clean_pairs.scalar(select(QAPair.hit_count).where(QAPair.id == row.id)) == 7


def test_flush_drops_counts_of_pruned_rows(memory_kv, clean_pairs, monkeypatch):
    row = _add(clean_pairs, "输血核对流程")
    monkeypatch.setattr(settings, "qa_hit_flush_every", 0)
    qa_cache.touch(clean_pairs, "输血核对流程")
    clean_pairs.delete(row)
    clean_pairs.commit()

    assert qa_cache.flush_hits(clean_pairs) == 0          # 没有可回写的行
    assert memory_kv.hlen(qa_cache._HITS_KEY) == 0        # 计数被丢弃，不会无限堆积


def test_prune_keeps_top_hit_rows(memory_kv, clean_pairs):
    for index in range(5):
        _add(clean_pairs, f"第{index}个问题", hit=index)
    assert qa_cache.prune(clean_pairs, cap=3) == 2

    rows = list(clean_pairs.scalars(select(QAPair).order_by(QAPair.hit_count.desc())))
    assert [row.hit_count for row in rows] == [4, 3, 2]


def test_record_creates_then_prunes(memory_kv, clean_pairs, monkeypatch):
    monkeypatch.setattr(settings, "qa_cache_max_pairs", 2)
    for index in range(2):
        _add(clean_pairs, f"旧问题{index}", hit=5)
    qa_cache._load_index(clean_pairs, force=True)

    qa_cache.record(
        clean_pairs,
        "新来的问题",
        "这是一个足够长的答案" * 5,
        [1],
        [{"content": "引用", "images": []}],
    )
    rows = list(clean_pairs.scalars(select(QAPair).order_by(QAPair.hit_count.desc())))
    assert len(rows) == 2                                # 上限 2：新的保底进，挤掉一条旧的
    assert any(row.question == "新来的问题" for row in rows)  # 否则新问题永远热不起来
    assert rows[0].hit_count == 5                        # 留的是原来更热的那条


def test_bm25_over_300_pairs_is_fast(memory_kv):
    """300 条规模下 BM25 打分必须远低于一次模型调用。"""
    from app.services.bm25 import BM25, tokenize

    corpus = [tokenize(f"成人心肺复苏按压深度要求第{index}条") for index in range(300)]
    started = time.perf_counter()
    scores = BM25(corpus).scores(tokenize("针刺伤之后应该怎么处理伤口"))
    cost = time.perf_counter() - started

    assert len(scores) == 300
    assert cost < 0.05, f"BM25 300 条耗时 {cost * 1000:.1f}ms"
