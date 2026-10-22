"""高频问答缓存运维工具：看规模、重建 Redis 索引、按上限淘汰、导入问答对、实测命中耗时。

用法：
    python scripts/ops/qa_cache_tool.py stats
    python scripts/ops/qa_cache_tool.py rebuild
    python scripts/ops/qa_cache_tool.py prune --cap 300
    python scripts/ops/qa_cache_tool.py import data/qa_seed.json --kb 18
    python scripts/ops/qa_cache_tool.py bench --kb 18

`import` 的 JSON 支持两种形态：
    [{"question": "...", "answer": "...", "kb_ids": [18]}, ...]
    [{"question": "...", "answer": "..."}]        # 缺省用 --kb 补
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import delete, func, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.qa import QAPair  # noqa: E402
from app.services import qa_cache  # noqa: E402
from app.services.cache import get_kv  # noqa: E402


def cmd_stats() -> None:
    db = SessionLocal()
    try:
        kv = get_kv()
        snap = qa_cache.stats(db)
        print(f"缓存后端      : {snap['backend']}")
        print(f"MySQL 条数    : {snap['pairs']} / 上限 {snap['max_pairs']}")
        print(f"Redis 索引    : {snap['indexed']} 条（qa:index）")
        print(f"Redis 精确表  : {snap['exact_keys']} 个 field（qa:q）")
        print(f"待回写命中数  : {snap['pending_keys']} 个问题 / 共 {snap['pending_total']} 次")
        print(f"命中阈值      : {snap['threshold']}")
        rows = db.scalars(select(QAPair).order_by(QAPair.hit_count.desc()).limit(10))
        print("\nTop 10 高频问答：")
        for rank, row in enumerate(rows, 1):
            print(f"  {rank:>2}. [{row.hit_count:>3}] {row.question[:40]}  kb={row.kb_ids}")
    finally:
        db.close()


def cmd_rebuild() -> None:
    db = SessionLocal()
    try:
        qa_cache._invalidate()
        started = time.perf_counter()
        index = qa_cache._load_index(db, force=True)
        cost = (time.perf_counter() - started) * 1000
        kv = get_kv()
        print(f"重建完成：{len(index)} 条，耗时 {cost:.1f} ms")
        print(f"  qa:index 存在 = {bool(kv.get(qa_cache._INDEX_KEY))}")
        print(f"  qa:q field 数 = {kv.hlen(qa_cache._EXACT_KEY)}")
    finally:
        db.close()


def cmd_prune(cap: int) -> None:
    db = SessionLocal()
    try:
        removed = qa_cache.prune(db, cap=cap)
        remaining = int(db.scalar(select(func.count()).select_from(QAPair)) or 0)
        print(f"淘汰 {removed} 条，剩余 {remaining} 条（上限 {cap}）")
        qa_cache._invalidate()
    finally:
        db.close()


def cmd_import(path: Path, kb: int | None) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("JSON 必须是数组：[{\"question\": ..., \"answer\": ...}, ...]")

    db = SessionLocal()
    added = updated = skipped = 0
    try:
        for item in payload:
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            if not question or not answer:
                skipped += 1
                continue
            key = qa_cache.normalize(question)
            row = db.scalar(select(QAPair).where(QAPair.question_key == key))
            if row is None:
                db.add(
                    QAPair(
                        question=question[:500],
                        question_key=key,
                        answer=answer,
                        kb_ids=list(item.get("kb_ids") or ([kb] if kb else [])),
                        contexts=item.get("contexts") or [],
                        plan=item.get("plan") or {},
                        hit_count=int(item.get("hit_count") or 1),
                    )
                )
                added += 1
            else:
                row.answer = answer
                if item.get("kb_ids") or kb:
                    row.kb_ids = list(item.get("kb_ids") or [kb])
                if item.get("contexts"):
                    row.contexts = item["contexts"]
                updated += 1
        db.commit()
        pruned = qa_cache.prune(db)
        qa_cache._invalidate()
        total = int(db.scalar(select(func.count()).select_from(QAPair)) or 0)
        print(f"导入完成：新增 {added}，更新 {updated}，跳过 {skipped}，淘汰 {pruned}，当前共 {total} 条")
        if pruned:
            print("提示：超过 QA_CACHE_MAX_PAIRS，已按命中数淘汰低频条目")
    finally:
        db.close()


def cmd_clear(confirm: bool) -> None:
    if not confirm:
        raise SystemExit("这会清空所有高频问答，确认请加 --yes")
    db = SessionLocal()
    try:
        db.execute(delete(QAPair))
        db.commit()
        qa_cache._invalidate()
        print("已清空 qa_pairs 与 Redis 索引")
    finally:
        db.close()


def cmd_bench(kb: int, question: str) -> None:
    """直接测缓存链路耗时（不含 HTTP 与前端渲染）。"""
    db = SessionLocal()
    try:
        qa_cache._load_index(db)
        for label, text in (("原始问法", question), ("换个问法", f"请问 {question}")):
            started = time.perf_counter()
            hit = qa_cache.lookup(db, text, [kb])
            cost = (time.perf_counter() - started) * 1000
            state = f"命中({hit['source']}, score={hit['score']})" if hit else "未命中 → 走 RAG"
            print(f"{label}: {cost:6.2f} ms  {state}")
        started = time.perf_counter()
        miss = qa_cache.lookup(db, "今天天气怎么样适合洗车吗", [kb])
        print(f"无关问题: {(time.perf_counter() - started) * 1000:6.2f} ms  "
              f"{'意外命中' if miss else '未命中 → 走 RAG'}")
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="高频问答缓存运维工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="查看缓存规模与高频榜单")
    sub.add_parser("rebuild", help="让 Redis 索引失效并从 MySQL 重建")

    prune = sub.add_parser("prune", help="按上限淘汰低频问答")
    prune.add_argument("--cap", type=int, default=settings.qa_cache_max_pairs)

    importer = sub.add_parser("import", help="从 JSON 导入问答对")
    importer.add_argument("path", type=Path)
    importer.add_argument("--kb", type=int, default=None, help="缺省知识库 ID")

    cleaner = sub.add_parser("clear", help="清空所有问答缓存")
    cleaner.add_argument("--yes", action="store_true")

    bench = sub.add_parser("bench", help="实测命中的耗时")
    bench.add_argument("--kb", type=int, default=18)
    bench.add_argument("--question", default="内部培训考核规则是啥?")

    args = parser.parse_args()
    if args.cmd == "stats":
        cmd_stats()
    elif args.cmd == "rebuild":
        cmd_rebuild()
    elif args.cmd == "prune":
        cmd_prune(args.cap)
    elif args.cmd == "import":
        cmd_import(args.path, args.kb)
    elif args.cmd == "clear":
        cmd_clear(args.yes)
    elif args.cmd == "bench":
        cmd_bench(args.kb, args.question)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
