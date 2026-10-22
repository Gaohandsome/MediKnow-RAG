"""文档与文档块模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False, comment="服务器存储路径")
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="文件类型")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="文件大小(字节)")

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", comment="pending/processing/completed/failed"
    )
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="失败原因")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    chunks = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Document id={self.id} filename={self.filename} status={self.status}>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="块序号")
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=-1, comment="所属页码/页签")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="块内容")
    parent_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        index=True,
        comment="父块 ID（document_id*100000 + 文档内父块序号）",
    )
    parent_content: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="父块内容（整页原文 + 关联图片标记）"
    )
    image_urls: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="关联图片 JSON：[{caption,url,kind}]"
    )
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    milvus_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True, comment="Milvus 主键")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    document = relationship("Document", back_populates="chunks")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DocumentChunk id={self.id} doc={self.document_id} index={self.chunk_index}>"
