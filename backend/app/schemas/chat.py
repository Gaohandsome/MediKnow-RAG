"""对话相关数据结构。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionCreate(BaseModel):
    name: str = Field(default="新对话", max_length=128, description="会话名称")
    kb_ids: list[int] = Field(default_factory=list, description="关联知识库")
    model: str | None = Field(default=None, description="大模型")
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0.01, le=1)
    max_tokens: int | None = Field(default=None, ge=16, le=8192)
    history_rounds: int | None = Field(default=None, ge=0, le=20)


class SessionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    kb_ids: list[int] | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0.01, le=1)
    max_tokens: int | None = Field(default=None, ge=16, le=8192)
    history_rounds: int | None = Field(default=None, ge=0, le=20)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    model: str
    temperature: float
    top_p: float
    max_tokens: int
    history_rounds: int
    kb_ids: list[int]
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ContextItem(BaseModel):
    chunk_id: int
    document_id: int
    document_name: str
    knowledge_base_id: int
    knowledge_base_name: str
    content: str
    score: float


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    contexts: list[dict] = Field(default_factory=list)
    plan: dict = Field(default_factory=dict)
    latency_ms: int
    created_at: datetime


class ChatRequest(BaseModel):
    session_id: int | None = Field(default=None, description="会话ID，为空则自动新建")
    question: str = Field(..., min_length=1, max_length=4000, description="用户问题")
    kb_ids: list[int] = Field(default_factory=list, description="参与检索的知识库")
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0.01, le=1)
    max_tokens: int | None = Field(default=None, ge=16, le=8192)
    history_rounds: int | None = Field(default=None, ge=0, le=20)
    top_k: int | None = Field(default=None, ge=1, le=20, description="召回条数")
    use_rerank: bool | None = Field(default=None, description="是否启用重排")

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        return value
