"""把扩充后的院内文档同步到知识库并重跑解析入库。

解决的问题：老版本文档每篇只有约 900 字，Markdown 解析器把整篇当作 1 个父块，
父块粒度等于文档粒度，检索「命中一段」与「命中整篇」没有区别，评估指标会被拉饱和。

本脚本做三件事：
1. 把 data/medical_docs/*.md 的**新内容**覆盖到知识库里对应的存储文件（按文件名匹配，不新增文档）；
2. 调整知识库的切块参数（默认 350/80），让章节级父块内部再切出多个子块；
3. 只重跑 Markdown 文档的解析入库（PDF 扫描件不重跑，避免重新 OCR 依赖大模型）。

用法：
    python scripts/data/expand_medical_docs.py --dry-run     # 只看会对哪些文档做什么
    python scripts/data/expand_medical_docs.py               # 同步 + 重跑
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from loguru import logger  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.knowledge import KnowledgeBase  # noqa: E402
from app.services.document_service import ingest_document  # noqa: E402

SRC_DIR = ROOT / "data" / "medical_docs"


def main() -> int:
    parser = argparse.ArgumentParser(description="同步扩充文档并重跑解析入库")
    parser.add_argument("--kb", type=int, default=18, help="知识库 ID")
    parser.add_argument("--chunk-size", type=int, default=350, help="子块大小")
    parser.add_argument("--chunk-overlap", type=int, default=80, help="子块重叠")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件、不入库")
    parser.add_argument("--no-reindex", action="store_true", help="只同步文件与参数，不重跑解析")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss} {message}")

    db = SessionLocal()
    try:
        kb = db.get(KnowledgeBase, args.kb)
        if kb is None:
            print(f"知识库不存在：{args.kb}")
            return 1

        docs = list(
            db.scalars(
                select(Document)
                .where(Document.knowledge_base_id == kb.id)
                .order_by(Document.id)
            )
        )
        by_name = {doc.filename: doc for doc in docs}

        targets: list[Document] = []
        for path in sorted(SRC_DIR.glob("*.md")):
            doc = by_name.get(path.name)
            if doc is None:
                print(f"跳过（知识库中没有对应文档）：{path.name}")
                continue
            targets.append(doc)
            print(
                f"同步 doc={doc.id} {doc.filename}："
                f"{Path(doc.stored_path).stat().st_size} 字节 -> {path.stat().st_size} 字节"
            )
            if not args.dry_run:
                Path(doc.stored_path).write_bytes(path.read_bytes())

        print(
            f"\n知识库「{kb.name}」切块参数：{kb.chunk_size}/{kb.chunk_overlap} -> "
            f"{args.chunk_size}/{args.chunk_overlap}"
        )
        if not args.dry_run:
            kb.chunk_size = args.chunk_size
            kb.chunk_overlap = args.chunk_overlap
            db.commit()

        if args.no_reindex or args.dry_run:
            print("已跳过重跑解析（--dry-run / --no-reindex）")
            return 0

        for index, doc in enumerate(targets, start=1):
            media_dir = ROOT / "data" / "media" / str(doc.id)
            if media_dir.exists():
                shutil.rmtree(media_dir, ignore_errors=True)
            print(f"[{index}/{len(targets)}] 重新解析 doc={doc.id} {doc.filename}")
            ingest_document(doc.id)
            # ingest_document 内部用独立会话提交，外层会话在 REPEATABLE READ 下读到的是旧快照，
            # 因此回读必须另开一个会话，否则打印出来的切块数永远是入库前的值。
            probe = SessionLocal()
            try:
                fresh = probe.get(Document, doc.id)
                print(
                    f"    -> {fresh.status}，切块 {fresh.chunk_count}，{fresh.char_count} 字",
                    flush=True,
                )
            finally:
                probe.close()

        db.expire_all()
        probe = SessionLocal()
        try:
            fresh_kb = probe.get(KnowledgeBase, kb.id)
            print(f"\n完成：文档 {fresh_kb.document_count} 份，切块 {fresh_kb.chunk_count} 个")
        finally:
            probe.close()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
