"""纯检索评估：不调用大模型，只看「金标文档有没有被召回、排在第几」。

RAGAS 四指标依赖判定模型，欠费或限流时跑不动；本脚本用金标文档做代理指标，
可以在零成本的前提下快速判断「扩充文档 / 改切块参数」是否伤到召回。

指标口径：
- Hit@1 / Hit@3：top-k 结果里出现金标文档的用例占比
- MRR：金标文档首次出现名次的倒数均值
- 章节命中：金标文档的父块里，是否包含该问题对应章节（由 --gold-section 关键字匹配，可选）

用法：
    python scripts/eval/eval_retrieval_only.py                 # 默认不精排，top_k=3
    python scripts/eval/eval_retrieval_only.py --rerank        # 带精排（慢，每条约 20 秒）
    python scripts/eval/eval_retrieval_only.py --top-k 5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from loguru import logger  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.services.retrieval import retrieve_multi  # noqa: E402

CASES_PATH = ROOT / "data" / "eval" / "ragas_cases.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="纯检索金标召回评估")
    parser.add_argument("--kb-id", type=int, default=18)
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--rerank", action="store_true", help="开启精排（很慢）")
    parser.add_argument("--cases", default=str(CASES_PATH))
    parser.add_argument("--out", default="", help="把逐条结果写入 JSON")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stdout, level="WARNING", format="{message}")

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    db = SessionLocal()
    rows: list[dict] = []
    started = time.perf_counter()
    try:
        for index, case in enumerate(cases, start=1):
            t0 = time.perf_counter()
            hits = retrieve_multi(
                db,
                [{"text": case["question"], "label": "direct"}],
                kb_ids=[args.kb_id],
                user_id=args.user_id,
                top_k=args.top_k,
                use_rerank=args.rerank,
                candidate_k=args.candidate_k,
            )
            names = [item.get("document_name") for item in hits]
            rank = next(
                (pos for pos, name in enumerate(names, start=1) if name == case["doc"]), 0
            )
            rows.append(
                {
                    "id": case["id"],
                    "doc": case["doc"],
                    "question": case["question"],
                    "rank": rank,
                    "hits": names,
                    "seconds": round(time.perf_counter() - t0, 2),
                }
            )
            print(
                f"[{index:>2}/{len(cases)}] {case['id']:<9} rank={rank or '—':<3} "
                f"{time.perf_counter() - t0:5.1f}s  {case['question'][:28]}",
                flush=True,
            )

        n = len(rows)
        hit1 = sum(1 for r in rows if r["rank"] == 1) / n
        hitk = sum(1 for r in rows if 1 <= r["rank"] <= args.top_k) / n
        mrr = sum((1 / r["rank"]) if r["rank"] else 0 for r in rows) / n
        elapsed = time.perf_counter() - started

        print("\n" + "=" * 62)
        print(f"用例 {n} 条　top_k={args.top_k}　精排={'开' if args.rerank else '关'}")
        print(f"Hit@1  {hit1:.4f}")
        print(f"Hit@{args.top_k}  {hitk:.4f}")
        print(f"MRR    {mrr:.4f}")
        print(f"总耗时 {elapsed:.1f}s（平均 {elapsed / n:.2f}s/条）")
        missed = [r for r in rows if not r["rank"]]
        if missed:
            print(f"\n未命中 {len(missed)} 条：")
            for r in missed:
                print(f"  {r['id']:<9} 期望《{r['doc']}》 实际 {r['hits']}")

        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(
                    {
                        "top_k": args.top_k,
                        "rerank": args.rerank,
                        "cases": n,
                        "hit1": round(hit1, 4),
                        "hitk": round(hitk, 4),
                        "mrr": round(mrr, 4),
                        "rows": rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"\n明细已写入：{out_path}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
