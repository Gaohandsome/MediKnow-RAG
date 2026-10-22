"""知识库模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="知识库名称")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="知识库描述")

    # 解析参数
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=500, comment="切块大小")
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=100, comment="重叠大小")
    retrieval_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="hybrid", comment="检索方式：dense 稠密 / hybrid 混合"
    )

    # 统计与向量集合
    collection_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="Milvus 集合名")
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    documents = relationship(
        "Document", back_populates="knowledge_base", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<KnowledgeBase id={self.id} name={self.name} mode={self.retrieval_mode}>"
