"""文档与文档块数据结构。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    error_message: str
    chunk_count: int
    char_count: int
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentOut):
    knowledge_base_name: str = ""


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    knowledge_base_id: int
    chunk_index: int
    content: str
    char_count: int
    created_at: datetime
    updated_at: datetime


class ChunkUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000, description="修改后的块内容")


class ChunkPage(BaseModel):
    items: list[ChunkOut]
    total: int
    page: int
    page_size: int


class ParseParam(BaseModel):
    """文档解析参数（可覆盖知识库默认值）。"""

    chunk_size: int = Field(default=500, ge=100, le=4000, description="切块大小")
    chunk_overlap: int = Field(default=100, ge=0, le=1000, description="重叠大小")
    retrieval_mode: str = Field(default="hybrid", pattern="^(dense|hybrid)$", description="稠密检索或混合检索")


class UploadResult(BaseModel):
    document: DocumentOut
    message: str = "上传并解析成功"
