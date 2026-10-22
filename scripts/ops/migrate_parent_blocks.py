"""补齐父块：给 `document_chunks` 加 `parent_id` 列，并把全部文档重新入库。

父块改动涉及三处：MySQL 的 `parent_id`、Milvus 动态字段的 `parent_id/parent_content`、
以及检索侧的「按父块去重 + query × 父块精排」。老数据没有 `parent_id`，
必须重新解析一遍才能真正生效。

用法：
    python scripts/ops/migrate_parent_blocks.py            # 只体检
    python scripts/ops/migrate_parent_blocks.py --apply    # 加列 + 重新入库
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import func, select, text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document, DocumentChunk  # noqa: E402
from app.services.document_service import ingest_document  # noqa: E402
from app.services.vector_store import get_vector_store  # noqa: E402


def has_column() -> bool:
    with SessionLocal() as db:
        return bool(
            db.execute(
                text(
                    "select count(*) from information_schema.columns "
                    "where table_schema = database() and table_name = 'document_chunks' "
                    "and column_name = 'parent_id'"
                )
            ).scalar()
        )


def ensure_column() -> bool:
    """给 document_chunks 补 parent_id 列，已存在返回 False。"""
    if has_column():
        return False
    with SessionLocal() as db:
        db.execute(
            text(
                "alter table document_chunks add column parent_id bigint not null default 0 "
                "comment '父块 ID（document_id*100000 + 文档内父块序号）'"
            )
        )
        db.execute(text("alter table document_chunks add index ix_document_chunks_parent_id (parent_id)"))
        db.commit()
    return True


def report() -> None:
    with SessionLocal() as db:
        total = int(db.scalar(select(func.count(DocumentChunk.id))) or 0)
        # 列可能还没加，用原始 SQL 避免 ORM 映射报错
        if has_column():
            with_parent = int(
                db.execute(
                    text("select count(*) from document_chunks where parent_id > 0")
                ).scalar()
                or 0
            )
            parents = int(
                db.execute(
                    text("select count(distinct parent_id) from document_chunks where parent_id > 0")
                ).scalar()
                or 0
            )
        else:
            with_parent = parents = 0
        docs = int(db.scalar(select(func.count(Document.id))) or 0)
    print(f"文档 {docs} 个 / 子块 {total} 个 / 已带 parent_id {with_parent} 个 / 父块 {parents} 个")
    store = get_vector_store()
    collection = store.collection_name()
    if store.has_collection(collection):
        print(f"Milvus 实体数：{store.count(collection)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="补齐父块（MySQL 列 + Milvus 动态字段）")
    parser.add_argument("--apply", action="store_true", help="真正执行：加列并重新入库")
    args = parser.parse_args()

    print("== 迁移前 ==")
    report()

    if not args.apply:
        print("\n体检模式。加 --apply 执行：补 parent_id 列 → 全部文档重新入库。")
        return 0

    added = ensure_column()
    print(f"\nparent_id 列：{'已新增' if added else '已存在'}")

    with SessionLocal() as db:
        docs = list(db.scalars(select(Document).order_by(Document.id)))
    ready = [doc for doc in docs if Path(doc.stored_path).exists()]
    print(f"待重新入库：{len(ready)}/{len(docs)} 个文档")

    failed: list[int] = []
    for index, doc in enumerate(ready, start=1):
        print(f"[{index}/{len(ready)}] doc={doc.id} {doc.filename} ...", flush=True)
        try:
            ingest_document(doc.id)
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] 失败：{exc}")
            failed.append(doc.id)

    print("\n== 迁移后 ==")
    report()
    if failed:
        print(f"[!] 以下文档入库失败，请在界面上逐个「重新解析」：{failed}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
