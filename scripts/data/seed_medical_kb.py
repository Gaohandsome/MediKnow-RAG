"""把院内演示文档批量灌入指定知识库（解析 → 切块 → 向量化 → Milvus）。

说明：跳过同名文档，可重复执行。解析串行执行，CPU 向量化较慢，请耐心等待。
用法：
    python scripts/data/seed_medical_kb.py --username <你的注册账号> --kb "院内知识库（演示）"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from loguru import logger  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.knowledge import KnowledgeBase  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.knowledge import KnowledgeBaseCreate  # noqa: E402
from app.services.document_service import create_document, ingest_document  # noqa: E402
from app.services.knowledge_service import create_knowledge_base  # noqa: E402

DEFAULT_FILES = [
    *sorted((ROOT / "data" / "medical_docs").glob("*.md")),
    ROOT / "data" / "医院员工培训守则.pdf",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="批量灌入院内演示文档")
    parser.add_argument("--username", required=True, help="知识库归属账号（你的登录账号）")
    parser.add_argument("--kb", default="院内知识库（演示）", help="知识库名称，不存在则创建")
    parser.add_argument("--files", nargs="*", default=None, help="自定义文件列表")
    args = parser.parse_args()

    files = [Path(p) for p in args.files] if args.files else DEFAULT_FILES
    files = [p for p in files if p.exists()]
    if not files:
        print("没有找到可灌入的文件")
        return 1

    logger.remove()
    logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss} {message}")

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == args.username))
        if user is None:
            print(f"账号不存在：{args.username}")
            return 1

        kb = db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.user_id == user.id, KnowledgeBase.name == args.kb
            )
        )
        if kb is None:
            kb = create_knowledge_base(
                db,
                user.id,
                KnowledgeBaseCreate(
                    name=args.kb,
                    description="院内制度与诊疗规范演示库（合成数据，不可用于临床决策）",
                    retrieval_mode="hybrid",
                    chunk_size=settings.rag_chunk_size,
                    chunk_overlap=settings.rag_chunk_overlap,
                ),
            )
            db.commit()
            print(f"已创建知识库：{kb.name}（id={kb.id}）")
        else:
            print(f"使用已有知识库：{kb.name}（id={kb.id}）")

        existing = {
            name
            for name in db.scalars(
                select(Document.filename).where(Document.knowledge_base_id == kb.id)
            )
        }

        todo = [p for p in files if p.name not in existing]
        print(f"待灌入 {len(todo)} 份 / 共 {len(files)} 份（跳过重复 {len(files) - len(todo)} 份）")

        for index, path in enumerate(todo, start=1):
            print(f"[{index}/{len(todo)}] {path.name} ...", flush=True)
            document = create_document(
                db,
                kb,
                user.id,
                path.name,
                path.read_bytes(),
                settings.rag_chunk_size,
                settings.rag_chunk_overlap,
                "hybrid",
            )
            db.commit()
            ingest_document(document.id)
            db.refresh(document)
            status = "成功" if document.status == "completed" else f"失败（{document.status}）"
            print(f"    -> {status}，切块 {document.chunk_count}，{document.char_count} 字", flush=True)

        db.refresh(kb)
        print(f"\n完成：知识库「{kb.name}」文档 {kb.document_count} 份，切块 {kb.chunk_count} 个")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
