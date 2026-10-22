"""图文问答链路的纯函数单测：父块标记、图片解析、表格转 Markdown。"""
from __future__ import annotations

from app.services.chunking import build_parent_content, split_blocks
from app.services.parsing import TextBlock, _table_to_markdown
from app.services.retrieval import extract_images

IMAGES = [
    {
        "caption": "图 1 成人心肺复苏标准急救流程",
        "url": "http://127.0.0.1:8001/api/v1/media/53/p4_f1.png",
        "kind": "figure",
    },
    {
        "caption": "表格（第4页）：要素／标准",
        "url": "http://127.0.0.1:8001/api/v1/media/53/p4_t1.png",
        "kind": "table",
    },
]


def test_build_parent_content_embeds_image_markers():
    parent = build_parent_content("第4页正文", IMAGES)
    assert parent.startswith("第4页正文")
    assert "[关联图片: 图 1 成人心肺复苏标准急救流程 / 图片链接: http://" in parent
    assert parent.count("[关联图片:") == 2


def test_extract_images_round_trip():
    parent = build_parent_content("正文", IMAGES)
    images = extract_images(parent)
    assert [item["url"] for item in images] == [item["url"] for item in IMAGES]
    assert images[0]["caption"] == IMAGES[0]["caption"]


def test_extract_images_ignores_plain_text():
    assert extract_images("没有任何图片标记的正文") == []
    assert extract_images("") == []


def test_split_blocks_builds_parent_for_every_block():
    """父块对所有块都生成：纯文本页也要「子块命中、父块进提示词」。"""
    with_image = TextBlock(text="带图页面正文。", page=4, images=IMAGES)
    plain = TextBlock(text="纯文字页面正文。", page=5)
    chunks = split_blocks([with_image, plain], chunk_size=100, chunk_overlap=0, document_id=9)

    assert chunks[0]["images"] == IMAGES
    assert "[关联图片:" in chunks[0]["parent_content"]
    assert chunks[1]["images"] == []
    assert chunks[1]["parent_content"] == "纯文字页面正文。"
    # 父块 ID = document_id*100000 + 文档内父块序号
    assert chunks[0]["parent_id"] == 900000
    assert chunks[1]["parent_id"] == 900001


def test_table_to_markdown_keeps_rows_and_columns():
    rows = [["要素", "标准"], ["按压深度", "5~6 cm"], ["按压频率", None]]
    markdown = _table_to_markdown(rows)
    assert markdown.splitlines()[0] == "| 要素 | 标准 |"
    assert "| 按压深度 | 5~6 cm |" in markdown
    # 空单元格补成空串，保持列数一致
    assert markdown.splitlines()[-1] == "| 按压频率 |  |"


def test_table_to_markdown_returns_empty_for_blank_table():
    assert _table_to_markdown([]) == ""
    assert _table_to_markdown([[None, None]]) == ""
