"""对话会话与对话消息模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="新对话", comment="会话名称")

    # 推理参数
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="qwen-max")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    top_p: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    history_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=5, comment="历史对话轮数")

    # 绑定的知识库
    kb_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list, comment="关联的知识库ID列表")

    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    messages = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatSession id={self.id} name={self.name}>"


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="user/assistant")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # 检索到的上下文（用于前端折叠展示与追溯）
    contexts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 本次问答的意图/检索策略/是否命中缓存
    plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    session = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatMessage id={self.id} role={self.role}>"
