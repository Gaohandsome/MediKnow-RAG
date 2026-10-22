"""文本切块：按段落/句子递归切分，支持重叠，尽量不切断语义。"""
from __future__ import annotations

import re

from app.services.parsing import TextBlock

# 句子分隔符，按优先级从强到弱
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ". ", "! ", "? ", "; ", "，", ", ", " "]


def _split_by_separator(text: str, separator: str) -> list[str]:
    if separator == "":
        return [text]
    parts = text.split(separator)
    if len(parts) == 1:
        return [text]
    # 把分隔符保留在前一段结尾，避免句子粘连
    results: list[str] = []
    for index, part in enumerate(parts):
        if index < len(parts) - 1:
            results.append(part + separator)
        elif part:
            results.append(part)
    return [item for item in results if item]


def _merge_pieces(pieces: list[str], chunk_size: int) -> list[str]:
    chunks: list[str] = []
    buffer = ""
    for piece in pieces:
        if not piece:
            continue
        if len(buffer) + len(piece) <= chunk_size:
            buffer += piece
            continue
        if buffer.strip():
            chunks.append(buffer.strip())
        # 单段仍超长则硬切
        while len(piece) > chunk_size:
            chunks.append(piece[:chunk_size].strip())
            piece = piece[chunk_size:]
        buffer = piece
    if buffer.strip():
        chunks.append(buffer.strip())
    return chunks


_MIN_CHUNK_CHARS = 120


def _merge_short(chunks: list[str], chunk_size: int) -> list[str]:
    """把过短的尾块并回前一块。

    章节末尾常剩一句半句，硬切成 30~80 字的块既捞不到有效信息，
    还会在向量库里制造噪声（短块与任何 query 的相似度都不稳定）。
    """
    if len(chunks) <= 1:
        return chunks
    merged: list[str] = [chunks[0]]
    for chunk in chunks[1:]:
        if len(chunk) < _MIN_CHUNK_CHARS and len(merged[-1]) + len(chunk) <= int(chunk_size * 1.5):
            merged[-1] = merged[-1] + chunk
        else:
            merged.append(chunk)
    return merged


def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 100) -> list[str]:
    """把单段文本切成若干块。"""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    if chunk_size <= 0:
        chunk_size = 500
    chunk_overlap = max(0, min(chunk_overlap, chunk_size - 1))

    pieces = [text]
    for separator in _SEPARATORS:
        next_pieces: list[str] = []
        for piece in pieces:
            if len(piece) <= chunk_size:
                next_pieces.append(piece)
            else:
                next_pieces.extend(_split_by_separator(piece, separator))
        pieces = next_pieces
        if all(len(piece) <= chunk_size for piece in pieces):
            break

    chunks = _merge_short(_merge_pieces(pieces, chunk_size), chunk_size)

    # 处理重叠：把上一块的尾部拼到下一块开头，保持检索上下文连贯
    if chunk_overlap > 0 and len(chunks) > 1:
        overlapped: list[str] = [chunks[0]]
        for index in range(1, len(chunks)):
            tail = overlapped[-1][-chunk_overlap:]
            # 只在语义边界处重叠，避免从半个词开始
            boundary = re.search(r"[。！？；\n，,]", tail)
            if boundary:
                tail = tail[boundary.end():]
            merged = (tail + chunks[index]).strip()
            overlapped.append(merged)
        chunks = overlapped

    return [chunk for chunk in chunks if chunk.strip()]


def _image_marker(caption: str, url: str) -> str:
    """父块里的图片标记，形如 `[关联图片: 图 1 流程 / 图片链接: http://...]`。"""
    return f"[关联图片: {caption} / 图片链接: {url}]"


# 父块 ID = document_id * 步长 + 文档内父块序号，十进制可反解，方便排查
_PARENT_STRIDE = 100_000


def parent_id_of(document_id: int, parent_index: int) -> int:
    """父块 ID：全局唯一、可反解成「哪个文档的第几个父块」。"""
    return int(document_id or 0) * _PARENT_STRIDE + int(parent_index)


def build_parent_content(text: str, images: list[dict] | None = None, title: str = "") -> str:
    """父块内容 = 原文 + 图片标记，供检索命中后回查原文与图片。

    title 非空时把文档标题补到父块开头：章节级父块单独拿出来看会缺失「这是哪份制度」，
    补一行标题既能让模型知道出处，也几乎不增加长度。
    """
    body = text.strip()
    parts: list[str] = []
    if title and not body.startswith(f"# {title}"):
        parts.append(f"# {title}")
    if body:
        parts.append(body)
    for item in images or []:
        url = (item or {}).get("url")
        if not url:
            continue
        parts.append(_image_marker((item.get("caption") or "示意图").strip(), url))
    return "\n\n".join(part for part in parts if part)


def split_blocks(
    blocks: list[TextBlock],
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    document_id: int = 0,
) -> list[dict]:
    """把解析结果切成带元信息的块（每块附带父块 ID 与父块全文）。

    父块 = 一个解析单元（PDF 的一页 / 一页 PPT / 整篇 Word），子块 = 页内切分的片段。
    父块对**所有**块都生成：纯文本页同样需要「子块命中、父块进提示词」。
    """
    results: list[dict] = []
    for parent_index, block in enumerate(blocks):
        images = getattr(block, "images", None) or []
        title = (getattr(block, "meta", None) or {}).get("title") or ""
        parent = build_parent_content(block.text, images, title=title)
        parent_id = parent_id_of(document_id, parent_index)
        for piece in split_text(block.text, chunk_size, chunk_overlap):
            results.append(
                {
                    "content": piece,
                    "page": block.page,
                    "char_count": len(piece),
                    "parent_id": parent_id,
                    "parent_content": parent,
                    "images": images,
                }
            )
    return results
