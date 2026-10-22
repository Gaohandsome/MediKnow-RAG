"""为「精确问答缓存」建表并给消息加计划列。

- 新建 qa_pairs 表（问答沉淀，BM25 命中用）
- chat_messages 增加 plan 列（意图/策略/缓存命中，供历史回看展示）

可重复执行：已存在则跳过。

用法：
    python scripts/ops/migrate_qa_schema.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import inspect, text  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.qa import QAPair  # noqa: E402


def ensure_qa_table() -> None:
    inspector = inspect(engine)
    if "qa_pairs" not in inspector.get_table_names():
        QAPair.__table__.create(bind=engine)
        print("已创建表：qa_pairs")
        return
    print("表 qa_pairs 已存在，检查列")
    columns = {column["name"] for column in inspector.get_columns("qa_pairs")}
    if "plan" in columns:
        print("列 qa_pairs.plan 已存在，跳过")
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE qa_pairs ADD COLUMN plan JSON NULL COMMENT '检索计划'"))
        conn.execute(text("UPDATE qa_pairs SET plan = JSON_OBJECT() WHERE plan IS NULL"))
        conn.execute(text("ALTER TABLE qa_pairs MODIFY COLUMN plan JSON NOT NULL"))
    print("已新增列：qa_pairs.plan")


def ensure_plan_column() -> None:
    inspector = inspect(engine)
    if "chat_messages" not in inspector.get_table_names():
        print("表 chat_messages 不存在，请先启动一次服务自动建表")
        return
    columns = {column["name"] for column in inspector.get_columns("chat_messages")}
    if "plan" in columns:
        print("列 chat_messages.plan 已存在，跳过")
        return
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE chat_messages ADD COLUMN plan JSON NULL COMMENT '意图/检索策略/缓存命中'")
        )
        conn.execute(text("UPDATE chat_messages SET plan = JSON_OBJECT() WHERE plan IS NULL"))
        conn.execute(text("ALTER TABLE chat_messages MODIFY COLUMN plan JSON NOT NULL"))
    print("已新增列：chat_messages.plan")


def main() -> int:
    Base.metadata  # 确保模型已加载
    ensure_qa_table()
    ensure_plan_column()
    print("迁移完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
