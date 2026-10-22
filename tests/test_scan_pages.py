"""扫描页兜底与图片地址刷新的纯函数单测（不联网、不写对象存储）。"""
from __future__ import annotations

import pytest

from app.services import media, parsing
from app.services.chat_service import _plain_contexts, _refresh_contexts
from app.services.media import refresh_url, strip_sign

SIGNED = (
    "https://shenzhen-ai8.s3.cn-south-1.qiniucs.com/52/p4_t1.png"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=86400&X-Amz-Signature=abc"
)


def test_strip_sign_removes_query():
    assert strip_sign(SIGNED) == "https://shenzhen-ai8.s3.cn-south-1.qiniucs.com/52/p4_t1.png"
    assert strip_sign("") == ""


def _use_qiniu(monkeypatch) -> None:
    """把配置切到「七牛 + S3 端点 + 私有桶」的组合（不联网，只算签名）。"""
    monkeypatch.setattr(media.settings, "media_storage", "qiniu")
    monkeypatch.setattr(media.settings, "media_url_mode", "signed")
    monkeypatch.setattr(media.settings, "qiniu_domain", "")
    monkeypatch.setattr(media.settings, "qiniu_s3_host", "shenzhen-ai8.s3.cn-south-1.qiniucs.com")
    monkeypatch.setattr(media.settings, "qiniu_access_key", "ak")
    monkeypatch.setattr(media.settings, "qiniu_secret_key", "sk")


def test_refresh_url_keeps_local_fallback():
    local = "http://127.0.0.1:8001/api/v1/media/52/p4_t1.png"
    assert refresh_url(local) == local
    assert refresh_url("") == ""


def test_refresh_url_resigns_object_storage(monkeypatch):
    """七牛模式下，旧签名要被剥掉再重签，不能叠加两个签名。"""
    _use_qiniu(monkeypatch)

    fresh = refresh_url(SIGNED)
    assert fresh.count("X-Amz-Signature=") == 1
    assert "abc" not in fresh
    assert "52/p4_t1.png" in fresh


def test_plain_contexts_drops_signature_before_saving(monkeypatch):
    monkeypatch.setattr(media.settings, "media_storage", "qiniu")
    contexts = [
        {
            "chunk_id": 1,
            "images": [{"caption": "表", "url": SIGNED, "kind": "table"}],
        },
        {"chunk_id": 2, "images": []},
    ]
    stored = _plain_contexts(contexts)
    assert "?" not in stored[0]["images"][0]["url"]
    assert stored[0]["images"][0]["caption"] == "表"
    # 原对象不被改写，SSE 下发的仍是可访问的签名地址
    assert contexts[0]["images"][0]["url"] == SIGNED
    assert stored[1]["images"] == []


def test_refresh_contexts_resigns_images(monkeypatch):
    _use_qiniu(monkeypatch)

    contexts = [{"chunk_id": 1, "images": [{"caption": "表", "url": SIGNED, "kind": "table"}]}]
    refreshed = _refresh_contexts(contexts)
    url = refreshed[0]["images"][0]["url"]
    assert url.startswith("https://shenzhen-ai8.s3.cn-south-1.qiniucs.com/52/p4_t1.png?")
    assert "abc" not in url


def test_transcribe_prompt_requires_table_structure():
    """转录提示词必须要求表格保结构，否则表格会被压成一句话。"""
    assert "Markdown 表格" in parsing._SCAN_PROMPT
    assert "不要总结" in parsing._SCAN_PROMPT


def test_scanned_page_produces_block(monkeypatch, tmp_path):
    """无文字层的页面：应产出带 vl_page 标记的块，并挂上整页图。"""
    pdf_path = tmp_path / "scan.pdf"
    _build_one_page_pdf(pdf_path)

    monkeypatch.setattr(parsing, "_transcribe_image", lambda image, hint="": "**识别结果**\n表格 5~6 cm")
    monkeypatch.setattr(
        media, "save_image", lambda image, key: f"http://127.0.0.1:8001/api/v1/media/{key}"
    )

    blocks = parsing.parse_file(pdf_path, "scan.pdf", document_id=999)
    assert len(blocks) == 1
    block = blocks[0]
    assert block.meta.get("source") == "vl_page"
    assert "由多模态模型识别" in block.text
    assert "5~6 cm" in block.text
    assert block.images[0]["kind"] == "page"
    assert block.images[0]["url"].endswith("p1_page.png")


def test_scan_page_without_text_still_keeps_image(monkeypatch, tmp_path):
    """转录失败也要留块和整页图，避免这一页彻底消失。"""
    pdf_path = tmp_path / "scan.pdf"
    _build_one_page_pdf(pdf_path)

    monkeypatch.setattr(parsing, "_transcribe_image", lambda image, hint="": "")
    monkeypatch.setattr(
        media, "save_image", lambda image, key: f"http://127.0.0.1:8001/api/v1/media/{key}"
    )

    blocks = parsing.parse_file(pdf_path, "scan.pdf", document_id=999)
    assert len(blocks) == 1
    assert "未能识别文字" in blocks[0].text
    assert blocks[0].images


def _build_one_page_pdf(path) -> None:
    """造一张只有图片、没有文字层的单页 PDF。"""
    io_module = __import__("io")
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (600, 400), "white")
    buffer = io_module.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    pdf_canvas = canvas.Canvas(str(path), pagesize=(300, 200))
    pdf_canvas.drawImage(ImageReader(buffer), 0, 0, width=300, height=200)
    pdf_canvas.showPage()
    pdf_canvas.save()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
