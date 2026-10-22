"""给共享集合开启动态字段（`$meta`），并把已有文档重新灌一遍。

Milvus 的动态字段只能在建集合时决定，无法给已存在的集合追加，
所以流程是：备份 → 删除集合 → 按新 schema 重建 → 逐文档重新解析入库。

用法：
    python scripts/ops/migrate_milvus_dynamic.py            # 只体检，不动数据
    python scripts/ops/migrate_milvus_dynamic.py --apply    # 真正执行
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.services.document_service import ingest_document  # noqa: E402
from app.services.vector_store import get_vector_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="为 Milvus 共享集合开启动态字段")
    parser.add_argument("--apply", action="store_true", help="真正执行迁移（默认只体检）")
    parser.add_argument("--backup-dir", default="data/backup", help="备份目录")
    args = parser.parse_args()

    store = get_vector_store()
    collection = store.collection_name()
    if not store.has_collection(collection):
        print(f"[!] 集合不存在：{collection}")
        return 1

    dynamic = store.supports_dynamic_field(collection)
    total = store.count(collection)
    print(f"集合：{collection}")
    print(f"实体数：{total}")
    print(f"动态字段：{'已开启' if dynamic else '未开启'}")

    with SessionLocal() as db:
        docs = list(db.scalars(select(Document).order_by(Document.id)))
    ready = [doc for doc in docs if Path(doc.stored_path).exists()]
    print(f"文档：{len(docs)} 个，源文件可读 {len(ready)} 个")
    missing = [doc.id for doc in docs if doc not in ready]
    if missing:
        print(f"  [!] 以下文档源文件缺失，重建后会丢失：{missing}")

    if dynamic:
        print("已开启动态字段，无需迁移。")
        return 0
    if not args.apply:
        print("\n当前为体检模式。加 --apply 执行：备份 → 删集合 → 重建 → 重新入库。")
        return 0

    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_file = backup_dir / f"milvus-{collection}-{stamp}.json"

    rows = store.client.query(
        collection_name=collection,
        filter="id > 0",
        output_fields=["kb_id", "document_id", "chunk_id", "page", "text"],
        limit=16384,
    )
    backup_file.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已备份 {len(rows)} 条标量数据 → {backup_file}")

    store.drop_collection(collection)
    store.ensure_collection(collection, "hybrid")
    print(f"集合已按新 schema 重建：{collection}")

    failed: list[int] = []
    for index, doc in enumerate(ready, start=1):
        print(f"[{index}/{len(ready)}] 重新入库 doc={doc.id} {doc.filename} ...", flush=True)
        try:
            ingest_document(doc.id)
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] 失败：{exc}")
            failed.append(doc.id)

    final_total = store.count(collection)
    print(f"\n完成：实体数 {final_total}（迁移前 {total}）")
    if failed:
        print(f"[!] 以下文档入库失败，请在界面上逐个「重新解析」：{failed}")
        return 2
    print("动态字段已开启，写入时会带上 images。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
