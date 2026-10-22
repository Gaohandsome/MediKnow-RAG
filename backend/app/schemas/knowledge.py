"""知识库数据结构。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="知识库名称")
    description: str = Field(default="", max_length=500, description="知识库描述")
    retrieval_mode: Literal["dense", "hybrid"] = Field(default="hybrid", description="稠密检索 / 混合检索")
    chunk_size: int = Field(default=500, ge=100, le=4000, description="切块大小")
    chunk_overlap: int = Field(default=100, ge=0, le=1000, description="重叠大小")

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("知识库名称不能为空")
        return value

    @field_validator("chunk_overlap")
    @classmethod
    def _check_overlap(cls, value: int, info) -> int:  # noqa: ANN001
        chunk_size = info.data.get("chunk_size", 500)
        if value >= chunk_size:
            raise ValueError("重叠大小必须小于切块大小")
        return value


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    retrieval_mode: str
    chunk_size: int
    chunk_overlap: int
    collection_name: str
    document_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseOption(BaseModel):
    """对话页选择知识库用的精简结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    document_count: int
    chunk_count: int
