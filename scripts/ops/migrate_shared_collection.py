"""把「每库一个集合」迁移为「所有知识库共用一个集合」。

背景：旧实现用 `前缀 + 知识库ID` 作为集合名（如 mediknow19），
导致配置里的 MILVUS_COLLECTION_PREFIX（mediknow）本身是空集合。
新实现以该前缀作为唯一集合名，靠 kb_id 字段隔离知识库。

本脚本：重建共享集合（缺 sparse 字段且为空时）→ 重新解析入库全部文档 → 删除旧的每库集合。

用法：
    python scripts/ops/migrate_shared_collection.py            # 迁移当前 .env 指向的库
    python scripts/ops/migrate_shared_collection.py --dry-run  # 只打印计划
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from loguru import logger  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.knowledge import KnowledgeBase  # noqa: E402
from app.services.document_service import ingest_document  # noqa: E402
from app.services.vector_store import get_vector_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移到共享 Milvus 集合")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不执行")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss} {message}")

    store = get_vector_store()
    client = store.client
    shared = store.collection_name()
    old_pattern = re.compile(rf"^{re.escape(shared)}\d+$")

    print(f"MySQL 库：{settings.mysql_database}")
    print(f"Milvus 库：{settings.milvus_database}")
    print(f"共享集合：{shared}")

    existing = client.list_collections()
    olds = [name for name in existing if old_pattern.match(name)]
    print(f"待迁移的旧集合：{olds or '无'}")

    if store.has_collection(shared):
        desc = client.describe_collection(collection_name=shared)
        fields = {field["name"] for field in desc.get("fields", [])}
        count = store.count(shared)
        required = {"kb_id", "document_id", "chunk_id", "page", "text", "dense", "sparse"}
        missing = required - fields
        print(f"共享集合已存在：字段={sorted(fields)} 实体数={count}")
        if missing:
            if count > 0:
                print(f"共享集合缺少字段 {sorted(missing)} 但已有数据，请手工处理后再运行")
                return 1
            if not args.dry_run:
                client.drop_collection(collection_name=shared)
                print(f"已删除缺少字段 {sorted(missing)} 的空集合，准备重建")
    else:
        print("共享集合不存在，将新建")

    db = SessionLocal()
    try:
        stale = list(db.scalars(select(KnowledgeBase).where(KnowledgeBase.collection_name != shared)))
        if stale:
            print(f"collection_name 需要改为 {shared} 的知识库：{[kb.id for kb in stale]}")

        docs = list(db.scalars(select(Document).where(Document.status == "completed").order_by(Document.id)))
        print(f"待重建向量的文档：{len(docs)} 份")
        if args.dry_run:
            for doc in docs:
                print(f"  - doc={doc.id} {doc.filename}（{doc.chunk_count} 块）")
            return 0

        store.ensure_collection(shared, "hybrid")

        # 数据库里的 collection_name 统一指向共享集合，保持接口返回一致
        if stale:
            db.execute(
                update(KnowledgeBase)
                .where(KnowledgeBase.collection_name != shared)
                .values(collection_name=shared)
            )
            db.commit()
            print(f"已把 {len(stale)} 个知识库的 collection_name 改为 {shared}")

        for index, doc in enumerate(docs, start=1):
            print(f"[{index}/{len(docs)}] 重建 {doc.filename}")
            ingest_document(doc.id)

        total = store.count(shared)
        print(f"共享集合当前实体数：{total}")

        for name in olds:
            if client.has_collection(collection_name=name):
                print(f"删除旧集合：{name}（实体 {store.count(name)}）")
                client.drop_collection(collection_name=name)

        print("迁移完成")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
