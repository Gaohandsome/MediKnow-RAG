"""查询链路单测：BM25 归一化、RRF 融合、父文档去重、检索计划变体。"""
from __future__ import annotations

import pytest

from app.services.bm25 import BM25, tokenize
from app.services.cache import get_json, get_kv, set_json
from app.services.qa_cache import normalize
from app.services.query_analysis import QueryPlan, heuristic_plan
from app.services.retrieval import dedupe_by_parent, rrf_fuse


def test_tokenize_mixes_chinese_bigram_and_english_word():
    tokens = tokenize("CPR 按压深度是多少？")
    assert "cpr" in tokens
    assert "按压" in tokens
    # 停用词被剔除
    assert "多少" not in tokens


def test_bm25_same_question_scores_near_one():
    corpus = [tokenize("胸外按压深度为5至6厘米"), tokenize("阿莫西林口服每次0.5克")]
    scores = BM25(corpus).scores(tokenize("胸外按压深度为5至6厘米"))
    assert scores[0] > 0.95
    assert scores[1] < 0.2


def test_bm25_ignores_polite_prefix_and_punctuation():
    corpus = [tokenize("多重耐药菌患者应实施接触隔离")]
    score = BM25(corpus).scores(tokenize("请问，多重耐药菌患者应实施接触隔离吗？"))[0]
    assert score > 0.9


def test_bm25_paraphrase_and_unrelated_stay_below_threshold():
    """换说法的同义问句不进缓存，交给向量检索，避免张冠李戴。"""
    corpus = [
        tokenize("多重耐药菌患者应实施接触隔离"),
        tokenize("危急值报告应在十分钟内完成"),
    ]
    model = BM25(corpus)
    paraphrase = model.scores(tokenize("多重耐药菌需要接触隔离吗"))
    unrelated = model.scores(tokenize("心肺复苏按压频率"))
    assert paraphrase[0] < 0.8
    assert unrelated[0] < 0.3


def test_rrf_fuse_promotes_chunk_hit_by_multiple_variants():
    group_a = [
        {"chunk_id": 1, "document_id": 10, "page": 1, "content": "A"},
        {"chunk_id": 2, "document_id": 10, "page": 2, "content": "B"},
    ]
    group_b = [
        {"chunk_id": 2, "document_id": 10, "page": 2, "content": "B"},
        {"chunk_id": 3, "document_id": 11, "page": 1, "content": "C"},
    ]
    for hit in group_a:
        hit["label"] = "direct"
    for hit in group_b:
        hit["label"] = "sub"
    fused = rrf_fuse([group_a, group_b])
    assert fused[0]["chunk_id"] == 2
    assert fused[0]["hits"] == 2
    assert set(fused[0]["labels"]) == {"direct", "sub"}


def test_dedupe_keeps_one_item_per_page_and_counts_siblings():
    items = [
        {"chunk_id": 1, "document_id": 5, "page": 3, "rrf": 0.03},
        {"chunk_id": 2, "document_id": 5, "page": 3, "rrf": 0.02},
        {"chunk_id": 3, "document_id": 5, "page": 4, "rrf": 0.01},
    ]
    kept = dedupe_by_parent(items)
    assert len(kept) == 2
    assert kept[0]["chunk_id"] == 1
    assert kept[0]["siblings"] == 1


def test_dedupe_does_not_collapse_documents_without_page():
    items = [
        {"chunk_id": 1, "document_id": 7, "page": -1, "rrf": 0.03},
        {"chunk_id": 2, "document_id": 7, "page": -1, "rrf": 0.02},
    ]
    assert len(dedupe_by_parent(items)) == 2


def test_plan_variants_always_keep_original_question_first():
    plan = QueryPlan(
        strategy="subquery",
        sub_queries=["子问题一", "子问题二"],
        simplified="简化问题",
        hyde="假设答案",
    )
    variants = plan.variants("原始问题", limit=3)
    assert variants[0] == {"text": "原始问题", "label": "direct"}
    assert len(variants) == 3
    labels = [item["label"] for item in variants]
    assert "simplified" in labels


def test_heuristic_detects_multi_question():
    plan = heuristic_plan("多重耐药菌患者要隔离多久？接触隔离需要戴什么防护用品？病房怎么消毒？")
    assert plan.strategy == "subquery"
    assert len(plan.sub_queries) >= 2


def test_heuristic_marks_short_greeting_as_no_retrieval():
    plan = heuristic_plan("你好")
    assert plan.need_retrieval is False
    assert plan.intent == "chitchat"


def test_heuristic_picks_coding_intent():
    assert heuristic_plan("python 里怎么读取环境变量").intent == "coding"


def test_normalize_strips_punctuation_and_width():
    assert normalize("多重耐药菌，要隔离多久？") == normalize("多重耐药菌要隔离多久")


def test_cache_roundtrip_uses_memory_backend(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "redis_enabled", False)
    kv = get_kv()
    assert kv.backend == "memory"
    set_json("pytest:key", {"a": 1}, ttl=60)
    assert get_json("pytest:key") == {"a": 1}
    kv.delete("pytest:key")
    assert get_json("pytest:key") is None


@pytest.mark.parametrize("question,expected", [("多重耐药菌患者要隔离多久", 0), ("你好", 0)])
def test_normalize_never_raises(question, expected):
    assert len(normalize(question)) >= expected
