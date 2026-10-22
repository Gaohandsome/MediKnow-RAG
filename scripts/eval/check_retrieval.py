"""检索自检：针对指定知识库跑一组问题，打印命中资料与稠密相关度。

用于扩充文档后快速确认「跨科室检索是否命中、无关问题是否被阈值拦住」。
用法：
    python scripts/eval/check_retrieval.py --kb-id 12
    python scripts/eval/check_retrieval.py --kb-id 12 --questions "急性心梗溶栓时间窗" "今天天气"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from loguru import logger  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.knowledge import KnowledgeBase  # noqa: E402
from app.services.embedding import get_embedder  # noqa: E402
from app.services.retrieval import retrieve  # noqa: E402
from app.services.vector_store import get_vector_store  # noqa: E402

DEFAULT_QUESTIONS = [
    "急性心梗的溶栓时间窗是多久",
    "成人胸外按压的深度和频率",
    "儿童发热布洛芬怎么给药",
    "10% 氯化钾能不能直接静推",
    "多重耐药菌患者什么时候能解除隔离",
    "危急值报告电话通知时限是几分钟",
    "今天北京天气怎么样",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库检索自检")
    parser.add_argument("--kb-id", type=int, required=True)
    parser.add_argument("--questions", nargs="*", default=None)
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, level="WARNING", format="{message}")

    questions = args.questions or DEFAULT_QUESTIONS
    db = SessionLocal()
    try:
        kb = db.get(KnowledgeBase, args.kb_id)
        if kb is None:
            print(f"知识库不存在：{args.kb_id}")
            return 1
        print(f"知识库：{kb.name}（文档 {kb.document_count} 份 / 切块 {kb.chunk_count} 个）")
        print(f"阈值 SAFETY_MIN_SCORE = {settings.safety_min_score}，top_k = {settings.rag_top_k}\n")

        embedder = get_embedder()
        store = get_vector_store()

        for question in questions:
            dense, _ = embedder.encode_query(question)
            score = store.max_dense_score(kb.collection_name, dense)
            hits = retrieve(db, question, [kb.id], kb.user_id, top_k=3)

            verdict = "命中" if score >= settings.safety_min_score else "拒答"
            print(f"【{question}】稠密最高分 {score:.3f} → {verdict}")
            if not hits:
                print("    （无召回）\n")
                continue
            for index, hit in enumerate(hits, start=1):
                snippet = hit["content"].replace("\n", " ")[:70]
                print(f"    {index}. {hit['document_name']} | 相关度 {hit.get('relevance', 0):.3f}")
                print(f"       {snippet}…")
            print()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
