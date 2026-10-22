"""精确问答对模型：支撑「BM25 命中即直接回答案」的缓存层。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QAPair(Base):
    """一次高质量问答的沉淀（问题归一化后去重，命中次数用于统计高频问题）。"""

    __tablename__ = "qa_pairs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(String(512), nullable=False, comment="原始问题")
    # 归一化后的问题（去标点/空白、小写），作为唯一键
    question_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False, comment="当时生成的答案")
    # 该答案对应的知识库，切换知识库后不能复用
    kb_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 命中时回放的参考资料（图片 URL 已去掉签名参数，读取时再签）
    contexts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 当时的检索计划（意图/策略/变体），命中时用于前端展示
    plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="被命中次数")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="llm", comment="llm/manual")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<QAPair id={self.id} hit={self.hit_count}>"
