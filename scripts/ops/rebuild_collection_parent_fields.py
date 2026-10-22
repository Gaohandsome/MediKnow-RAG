"""把 `parent_id` / `parent_content` 从动态字段升级成真实 schema 字段。

背景：Milvus 2.4.x 没有 `add_collection_field`（2.5+ 才有），集合建好后无法加列，
只能「备份 → 删集合 → 按新 schema 重建 → 重新入库」。

升级后的差异：
- Attu/Atlas 的「数据」页能直接看到 `parent_id` / `parent_content` 两列；
- `parent_id` 建了 INVERTED 索引，可按父块做标量过滤；
- `images` 仍留在动态字段里（纯展示用，不值得占 schema）。

用法：
    python scripts/ops/rebuild_collection_parent_fields.py            # 只体检
    python scripts/ops/rebuild_collection_parent_fields.py --apply    # 真正重建
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

from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.services.document_service import ingest_document  # noqa: E402
from app.services.vector_store import get_vector_store  # noqa: E402

WANTED = ("parent_id", "parent_content")


def field_names(store, collection: str) -> list[str]:
    info = store.client.describe_collection(collection_name=collection)
    return [field["name"] for field in info.get("fields", [])]


def main() -> int:
    parser = argparse.ArgumentParser(description="把父块字段升级为真实 schema 字段")
    parser.add_argument("--apply", action="store_true", help="真正重建集合（默认只体检）")
    parser.add_argument("--backup-dir", default="data/backup")
    args = parser.parse_args()

    store = get_vector_store()
    collection = store.collection_name()
    if not store.has_collection(collection):
        print(f"[!] 集合不存在：{collection}，直接建新 schema 即可")
        return 1

    names = field_names(store, collection)
    print(f"集合：{collection}  实体数：{store.count(collection)}")
    print(f"当前字段：{names}")
    print(f"动态字段：{store.supports_dynamic_field(collection)}")

    if all(item in names for item in WANTED):
        print("父块已是真实字段，无需重建。")
        return 0
    if not args.apply:
        print("\n体检模式。加 --apply 执行：备份 → 删集合 → 按新 schema 重建 → 重新入库。")
        return 0

    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{collection}-before-parent-fields-{datetime.now():%Y%m%d-%H%M%S}.json"
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
    print(f"已按新 schema 重建：{field_names(store, collection)}")

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

    total = store.count(collection)
    sample = store.client.query(
        collection_name=collection,
        filter="parent_id > 0",
        output_fields=["chunk_id", "parent_id", "parent_content"],
        limit=2,
    )
    print(f"\n完成：实体数 {total}")
    for row in sample:
        content = (row.get("parent_content") or "")[:50].replace("\n", " / ")
        print(f"  chunk={row.get('chunk_id')} parent_id={row.get('parent_id')} 父块「{content}…」")
    if failed:
        print(f"[!] 以下文档入库失败，请在界面上逐个「重新解析」：{failed}")
        return 2
    print("父块已变成真实字段，Attu 数据页应能看到两列。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
