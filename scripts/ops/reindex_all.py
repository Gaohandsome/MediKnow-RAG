"""重跑全部已完成文档的解析入库，补齐父块（parent_content）与关联图片。

改了切块/解析逻辑后运行一次即可；会把 data/media/{doc_id}/ 下的旧裁图清掉重生成。

用法：
    python scripts/ops/reindex_all.py            # 全部 completed 文档
    python scripts/ops/reindex_all.py --doc 51   # 指定文档
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

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.services.document_service import ingest_document  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="重跑文档解析与入库")
    parser.add_argument("--doc", type=int, help="只处理指定文档 ID")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss} {message}")

    db = SessionLocal()
    try:
        stmt = select(Document).where(Document.status == "completed").order_by(Document.id)
        if args.doc:
            stmt = select(Document).where(Document.id == args.doc)
        docs = list(db.scalars(stmt))
        print(f"待重跑文档：{len(docs)} 份（库={settings.mysql_database}）")
        if not docs:
            return 0

        for index, doc in enumerate(docs, start=1):
            media_dir = settings.media_path / str(doc.id)
            if media_dir.exists():
                shutil.rmtree(media_dir, ignore_errors=True)
            print(f"[{index}/{len(docs)}] 重新解析 doc={doc.id} {doc.filename}")
            ingest_document(doc.id)

        # 汇总带图块数
        from sqlalchemy import func

        from app.models.document import DocumentChunk

        total = int(db.scalar(select(func.count(DocumentChunk.id))) or 0)
        with_image = int(
            db.scalar(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.image_urls.is_not(None), DocumentChunk.image_urls != ""
                )
            )
            or 0
        )
        print(f"完成：块总数 {total}，带图片的块 {with_image}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
