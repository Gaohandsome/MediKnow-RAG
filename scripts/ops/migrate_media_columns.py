"""为图文问答增加列：document_chunks.parent_content / image_urls。

可重复执行：已存在的列会跳过。

用法：
    python scripts/ops/migrate_media_columns.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import inspect, text  # noqa: E402

from app.db.session import engine  # noqa: E402

COLUMNS = {
    "parent_content": "TEXT NULL COMMENT '父块内容（整页原文 + 关联图片标记）'",
    "image_urls": "TEXT NULL COMMENT '关联图片 JSON'",
}


def main() -> int:
    inspector = inspect(engine)
    if "document_chunks" not in inspector.get_table_names():
        print("表 document_chunks 不存在，请先启动一次服务自动建表")
        return 1

    existing = {column["name"] for column in inspector.get_columns("document_chunks")}
    with engine.begin() as conn:
        for name, ddl in COLUMNS.items():
            if name in existing:
                print(f"列已存在，跳过：{name}")
                continue
            conn.execute(text(f"ALTER TABLE document_chunks ADD COLUMN {name} {ddl}"))
            print(f"已新增列：{name}")
            conn.execute(
                text(f"UPDATE document_chunks SET {name} = '' WHERE {name} IS NULL")
            )

    # 用空串兜底后再收紧为 NOT NULL，与 ORM 定义保持一致
    with engine.begin() as conn:
        for name in COLUMNS:
            conn.execute(
                text(f"UPDATE document_chunks SET {name} = '' WHERE {name} IS NULL")
            )
            conn.execute(text(f"ALTER TABLE document_chunks MODIFY COLUMN {name} TEXT NOT NULL"))
    print("迁移完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
