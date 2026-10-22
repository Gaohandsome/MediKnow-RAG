"""文本切块与共享集合过滤条件的单元测试。"""
from __future__ import annotations

from app.services.chunking import split_blocks, split_text
from app.services.parsing import TextBlock
from app.services.vector_store import MilvusVectorStore


def test_split_text_short_content_returns_single_chunk():
    chunks = split_text("这是一个简短的句子。", chunk_size=200, chunk_overlap=20)
    assert chunks == ["这是一个简短的句子。"]


def test_split_text_empty_returns_list():
    assert split_text("   \n  ", 100, 10) == []


def test_split_text_respects_chunk_size():
    text = "。".join([f"这是第{i}段测试内容，用于验证切块逻辑是否正常工作" for i in range(60)]) + "。"
    chunks = split_text(text, chunk_size=120, chunk_overlap=20)
    assert len(chunks) > 1
    # 允许重叠部分带来的少量超出
    assert all(len(chunk) <= 120 + 20 for chunk in chunks)


def test_split_text_keeps_overlap_between_chunks():
    sentence = "公司差旅制度规定住宿标准按照城市级别执行。"
    text = sentence * 20
    chunks = split_text(text, chunk_size=100, chunk_overlap=30)
    assert len(chunks) >= 2
    # 上一块尾部内容应出现在下一块开头附近
    head = chunks[1][:60]
    tail = chunks[0][-60:]
    assert any(char in head for char in tail if char.strip())


def test_split_blocks_carries_page_number():
    blocks = [TextBlock(text="第一页内容，讲的是请假流程。", page=1), TextBlock(text="第二页内容，讲的是报销标准。", page=2)]
    chunks = split_blocks(blocks, chunk_size=50, chunk_overlap=0)
    assert [item["page"] for item in chunks] == [1, 2]
    assert chunks[0]["char_count"] == len(chunks[0]["content"])


def test_kb_expr_builds_milvus_filter():
    """共享集合靠 kb_id 过滤隔离知识库，表达式必须是合法的 Milvus 语法。"""
    assert MilvusVectorStore._kb_expr([12]) == "kb_id in [12]"
    assert MilvusVectorStore._kb_expr([12, 18]) == "kb_id in [12,18]"
    # 未指定知识库时不过滤
    assert MilvusVectorStore._kb_expr([]) == ""
    assert MilvusVectorStore._kb_expr(None) == ""
