"""父块相关纯函数单测：父块 ID 生成、按父块去重。"""
from __future__ import annotations

from app.services.chunking import parent_id_of
from app.services.retrieval import dedupe_by_parent


def test_parent_id_is_deterministic_and_document_scoped():
    assert parent_id_of(52, 0) == 5_200_000
    assert parent_id_of(52, 3) == 5_200_003
    # 不同文档、不同父块之间不会撞号
    assert len({parent_id_of(doc, idx) for doc in (1, 2) for idx in range(50)}) == 100
    # 可反解：除以步长得到文档号
    assert parent_id_of(52, 3) // 100_000 == 52


def test_dedupe_prefers_parent_id_over_page():
    """同一父块的两个子块（哪怕页号不同）只保留一条。"""
    items = [
        {"chunk_id": 1, "document_id": 5, "page": 3, "parent_id": 500001, "rrf": 0.03},
        {"chunk_id": 2, "document_id": 5, "page": 4, "parent_id": 500001, "rrf": 0.02},
        {"chunk_id": 3, "document_id": 5, "page": 5, "parent_id": 500002, "rrf": 0.01},
    ]
    kept = dedupe_by_parent(items)
    assert [item["chunk_id"] for item in kept] == [1, 3]
    assert kept[0]["siblings"] == 1


def test_dedupe_falls_back_to_page_for_legacy_rows():
    items = [
        {"chunk_id": 1, "document_id": 7, "page": 2, "rrf": 0.03},
        {"chunk_id": 2, "document_id": 7, "page": 2, "rrf": 0.02},
    ]
    kept = dedupe_by_parent(items)
    assert len(kept) == 1 and kept[0]["chunk_id"] == 1


def test_dedupe_keeps_chunks_apart_when_no_parent_and_no_page():
    items = [
        {"chunk_id": 1, "document_id": 8, "page": -1, "rrf": 0.03},
        {"chunk_id": 2, "document_id": 8, "page": -1, "rrf": 0.02},
    ]
    assert len(dedupe_by_parent(items)) == 2
