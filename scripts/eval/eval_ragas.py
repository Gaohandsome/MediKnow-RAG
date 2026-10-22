"""RAGAS 四指标评测：上下文精确度 / 上下文召回率 / 忠实度 / 回答相关性。

不依赖 ragas 包（它要拖 langchain/datasets，和本项目栈冲突），按 RAGAS 的原始定义
用「大模型判定 + 本地向量」自行实现，口径与 ragas 一致：

- Context Precision（有参考答案版）：逐条判定召回的资料是否有助于得到参考答案，
  再算 AP@K（相关项越靠前分越高）：
      AP = Σ(precision@k × rel_k) / 相关条数
- Context Recall：把参考答案拆成原子陈述，逐条判定能否在召回资料中找到依据，比值即分数。
- Faithfulness：把模型答案拆成原子陈述，逐条判定是否被召回资料支持，比值即分数。
- Answer Relevancy：让模型根据答案反推 N 个问题，与原问题算 bge-m3 稠密余弦，取均值。

用法：
    python scripts/eval/eval_ragas.py --stage all --limit 5          # 先小样本验证
    python scripts/eval/eval_ragas.py --stage run                    # 只跑检索+生成
    python scripts/eval/eval_ragas.py --stage judge                  # 只跑四指标（复用上次结果）
    python scripts/eval/eval_ragas.py --stage judge --resume data/eval/scores_1021_1000.json
                                                                # 只补跑上次没算出来的指标
    python scripts/eval/eval_ragas.py --stage all --no-rerank        # 关精排，快速回归

判定阶段是「50 条 × 4 指标 = 200 次调用」，并发一高就会撞阿里云的 429 limit_requests
（`limit_requests` 是 RPM 超限，和欠费不是一回事）。所以：
- 请求节奏由 `LLM_MAX_RPM`（默认 60）在 llm 层排队，不再靠线程数硬冲；
- 429 会指数退避重试，最多 `LLM_RATE_RETRIES` 次；
- `--workers` 只决定本地线程数，默认 3，压测时可降到 1。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from loguru import logger  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.embedding import get_embedder  # noqa: E402
from app.services.llm import complete  # noqa: E402
from app.services.prompt import build_rag_messages  # noqa: E402
from app.services.query_analysis import analyze  # noqa: E402
from app.services.retrieval import retrieve_multi  # noqa: E402

CASES_PATH = ROOT / "data" / "eval" / "ragas_cases_20.json"
OUT_DIR = ROOT / "data" / "eval"
METRICS = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]

# 判定用的模型：None = 跟主模型一致；用 --judge-model 换一个配额更宽松的模型
JUDGE_MODEL: str | None = None


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def load_cases(limit: int | None = None, ids: list[str] | None = None,
               path: Path | None = None) -> list[dict]:
    cases = json.loads((path or CASES_PATH).read_text(encoding="utf-8"))
    if ids:
        wanted = set(ids)
        cases = [case for case in cases if case["id"] in wanted]
    return cases[:limit] if limit else cases


def parse_json(raw: str) -> dict[str, Any]:
    """从模型输出里抠 JSON（兼容 ```json 围栏与前后废话）。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def judge(prompt: str, system: str = "你是严格的检索增强生成（RAG）评测员，只输出 JSON，不输出任何解释。") -> dict:
    raw = complete(
        [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        model=JUDGE_MODEL,
        temperature=0.0,
        max_tokens=1500,
    )
    return parse_json(raw)


def average_precision(flags: list[int]) -> float:
    """RAGAS 的 context precision：相关项排得越靠前分越高。"""
    total = sum(flags)
    if not total:
        return 0.0
    hits, score = 0, 0.0
    for index, flag in enumerate(flags, start=1):
        if flag:
            hits += 1
            score += hits / index
    return score / total


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def _trim(text: str, limit: int = 1200) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "…"


# --------------------------------------------------------------------------- #
# 阶段一：跑真实检索 + 生成
# --------------------------------------------------------------------------- #
def run_cases(cases: list[dict], kb_ids: list[int], user_id: int, use_rerank: bool, out_path: Path) -> None:
    done: set[str] = set()
    if out_path.exists():  # --resume：跳过已完成的
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])
        if done:
            logger.info(f"续跑：已有 {len(done)} 条结果")

    db = SessionLocal()
    try:
        with out_path.open("a", encoding="utf-8") as sink:
            for order, case in enumerate(cases, start=1):
                if case["id"] in done:
                    continue
                started = time.perf_counter()
                try:
                    plan = analyze(case["question"], [])
                    variants = plan.variants(case["question"]) if plan.need_retrieval else [
                        {"label": "direct", "text": case["question"]}
                    ]
                    middle = time.perf_counter()
                    contexts = retrieve_multi(
                        db,
                        variants,
                        kb_ids=kb_ids,
                        user_id=user_id,
                        use_rerank=use_rerank,
                    )
                    after_retrieval = time.perf_counter()
                    messages = build_rag_messages(case["question"], contexts, intent=plan.intent)
                    answer = complete(messages, temperature=0.1, max_tokens=900)
                    finished = time.perf_counter()
                    record = {
                        **case,
                        "variants": [item["label"] for item in variants],
                        "contexts": [
                            {
                                "document_name": item["document_name"],
                                "document_id": item["document_id"],
                                "page": item.get("page"),
                                "content": item.get("content", ""),
                                "parent_content": item.get("parent_content", ""),
                                "score": item.get("score"),
                            }
                            for item in contexts
                        ],
                        "answer": answer,
                        "timing": {
                            "rewrite_s": round(middle - started, 2),
                            "retrieval_s": round(after_retrieval - middle, 2),
                            "generate_s": round(finished - after_retrieval, 2),
                            "total_s": round(finished - started, 2),
                        },
                    }
                    sink.write(json.dumps(record, ensure_ascii=False) + "\n")
                    sink.flush()
                    print(
                        f"[{order:>2}/{len(cases)}] {case['id']:<10} 资料 {len(contexts)} 条  "
                        f"耗时 {record['timing']['total_s']:>5.1f}s"
                        f"（改写 {record['timing']['rewrite_s']:.1f} / 检索 {record['timing']['retrieval_s']:.1f}"
                        f" / 生成 {record['timing']['generate_s']:.1f}）",
                        flush=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"{case['id']} 执行失败：{exc}")
                    sink.write(json.dumps({**case, "answer": "", "contexts": [], "error": str(exc)},
                                          ensure_ascii=False) + "\n")
                    sink.flush()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 阶段二：四指标打分
# --------------------------------------------------------------------------- #
def score_context_precision(case: dict) -> float:
    contexts = case["contexts"]
    if not contexts:
        return 0.0
    listing = "\n".join(
        f"[{index}] 文档：{item['document_name']}{'，第' + str(item['page']) + '页' if (item.get('page') or -1) > 0 else ''}\n"
        f"    内容：{_trim(item.get('parent_content') or item.get('content'))}"
        for index, item in enumerate(contexts, start=1)
    )
    result = judge(
        f"【用户问题】\n{case['question']}\n\n"
        f"【参考答案】\n{case['ground_truth']}\n\n"
        f"【召回的资料】\n{listing}\n\n"
        f"任务：逐条判断每个资料对「得出参考答案」是否有用（能提供答案所需的关键事实即算有用，"
        f"只是主题相近但给不出答案的算无用）。\n"
        f"只输出 JSON：{{\"judgements\": [{{\"index\": 1, \"useful\": true}}, ...]}}，"
        f"必须覆盖全部 {len(contexts)} 条。"
    )
    flags = [0] * len(contexts)
    for item in result.get("judgements") or []:
        try:
            index = int(item.get("index")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(flags) and item.get("useful"):
            flags[index] = 1
    return average_precision(flags)


def _claims_score(text: str, contexts: list[dict], task: str) -> float:
    """把 text 拆成原子陈述，逐条核对是否能在资料中找到依据。"""
    if not text.strip():
        return 0.0
    if not contexts:
        return 0.0
    listing = "\n".join(
        f"[{index}] {_trim(item.get('parent_content') or item.get('content'), 900)}"
        for index, item in enumerate(contexts, start=1)
    )
    result = judge(
        f"【待检验的文本】\n{text}\n\n【参考资料】\n{listing}\n\n{task}\n"
        f"只输出 JSON：{{\"claims\": [{{\"claim\": \"...\", \"supported\": true}}, ...]}}"
    )
    claims = result.get("claims") or []
    if not claims:
        return 0.0
    supported = sum(1 for item in claims if item.get("supported"))
    return supported / len(claims)


def score_context_recall(case: dict) -> float:
    return _claims_score(
        case["ground_truth"],
        case["contexts"],
        "任务：把【待检验的文本】（参考答案）拆成若干条不可再分的原子陈述，"
        "逐条判断该陈述的事实能否在【参考资料】中找到依据（数字、剂量、时限必须一致才算支持）。",
    )


def score_faithfulness(case: dict) -> float:
    return _claims_score(
        case["answer"],
        case["contexts"],
        "任务：把【待检验的文本】（系统生成的回答）拆成若干条不可再分的原子陈述，"
        "逐条判断该陈述是否被【参考资料】明确支持（资料里没写、靠常识补的都算不支持）。",
    )


def score_answer_relevancy(case: dict, embedder) -> float:
    answer = case.get("answer") or ""
    if not answer.strip():
        return 0.0
    result = judge(
        f"【回答】\n{_trim(answer, 1500)}\n\n"
        f"任务：根据这段回答，反推 3 个它能回答的问题（不要照抄原问题）。\n"
        f"只输出 JSON：{{\"questions\": [\"...\", \"...\", \"...\"]}}"
    )
    generated = [str(item) for item in (result.get("questions") or []) if str(item).strip()][:3]
    if not generated:
        return 0.0
    dense, _ = embedder.encode([case["question"], *generated])
    base = dense[0]
    sims = [cosine(base, vector) for vector in dense[1:]]
    return max(0.0, sum(sims) / len(sims))


def regen_from(source: Path, out_path: Path) -> None:
    """复用已保存的检索结果，只重跑「生成」这一步。

    检索没变、只改了 prompt 里的参考资料组织方式时用它，省掉 20 分钟的检索开销。
    """
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    done: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])
    with out_path.open("a", encoding="utf-8") as sink:
        for order, row in enumerate(rows, start=1):
            if row["id"] in done or not row.get("contexts"):
                continue
            contexts = [
                {**item, "images": []}
                for item in row["contexts"]
            ]
            started = time.perf_counter()
            answer = complete(build_rag_messages(row["question"], contexts), temperature=0.1, max_tokens=900)
            sink.write(json.dumps({**row, "answer": answer, "regenerated": True}, ensure_ascii=False) + "\n")
            sink.flush()
            print(f"[{order:>2}/{len(rows)}] {row['id']:<10} 重生成 {time.perf_counter() - started:.1f}s",
                  flush=True)


def score_case(case: dict, embedder, existing: dict | None = None) -> dict:
    """给一条用例打四个分；`existing` 里已经算出来的指标直接复用，不重复花钱。"""
    scores: dict[str, Any] = dict(existing or {})
    for name, func in (
        ("context_precision", lambda: score_context_precision(case)),
        ("context_recall", lambda: score_context_recall(case)),
        ("faithfulness", lambda: score_faithfulness(case)),
        ("answer_relevancy", lambda: score_answer_relevancy(case, embedder)),
    ):
        if scores.get(name) is not None:
            continue
        try:
            scores[name] = round(float(func()), 4)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"{case['id']} 指标 {name} 计算失败：{exc}")
            scores[name] = None
    return {**{key: case[key] for key in ("id", "type", "doc", "question")},
            **{name: scores.get(name) for name in METRICS},
            "answer": case.get("answer", ""), "contexts": case.get("contexts", []),
            "timing": case.get("timing", {})}


def judge_cases(records: list[dict], workers: int = 3, existing: dict[str, dict] | None = None) -> list[dict]:
    embedder = get_embedder()
    existing = existing or {}

    def work(case: dict) -> dict:
        return score_case(case, embedder, existing.get(case["id"]))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        scored = list(pool.map(work, records))

    # 补跑：并发阶段仍被限流打掉的指标，串行重试一遍，避免 50 条只剩 34 条有效
    retry_idx = [i for i, item in enumerate(scored) if any(item.get(name) is None for name in METRICS)]
    if retry_idx:
        print(f"补跑 {len(retry_idx)} 条未算完的指标（串行重试）……", flush=True)
        for index in retry_idx:
            case = next(item for item in records if item["id"] == scored[index]["id"])
            scored[index] = score_case(case, embedder, scored[index])
    return scored


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def build_report(scored: list[dict], out_path: Path, meta: dict) -> dict:
    valid = [item for item in scored if all(item.get(name) is not None for name in METRICS)]
    summary = {
        name: round(sum(item[name] for item in valid) / len(valid), 4) if valid else 0.0
        for name in METRICS
    }
    per_doc: dict[str, list[dict]] = {}
    for item in valid:
        per_doc.setdefault(item["doc"], []).append(item)
    incomplete = [item["id"] for item in scored if any(item.get(name) is None for name in METRICS)]

    lines = [
        "# RAGAS 评测报告",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 样本数：{len(scored)}（有效 {len(valid)}）",
        f"- 用例集：{meta.get('cases', 'ragas_cases.json')}",
        (
            f"- 未完成：{len(incomplete)} 条（{'、'.join(incomplete)}）—— 多为 429 限流，"
            f"可用 `--stage judge --resume` 补跑"
            if incomplete
            else "- 未完成：0 条（全部样本四指标齐全）"
        ),
        f"- 知识库：kb_id={meta['kb_ids']}　精排：{'开' if meta['use_rerank'] else '关'}",
        f"- 生成模型：{settings.llm_default_model}　判定模型：{JUDGE_MODEL or settings.llm_default_model}",
        "",
        "## 总体得分",
        "",
        "| 指标 | 得分 | 说明 |",
        "| --- | --- | --- |",
        f"| 上下文精确度 Context Precision | **{summary['context_precision']:.4f}** | 相关资料是否排在前面（AP@K） |",
        f"| 上下文召回率 Context Recall | **{summary['context_recall']:.4f}** | 参考答案的事实有多少被召回 |",
        f"| 忠实度 Faithfulness | **{summary['faithfulness']:.4f}** | 回答的陈述有多少有资料支撑 |",
        f"| 回答相关性 Answer Relevancy | **{summary['answer_relevancy']:.4f}** | 回答是否切题（反推问题余弦） |",
        "",
        "## 按文档分组",
        "",
        "| 文档 | 样本 | 精确度 | 召回率 | 忠实度 | 相关性 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for doc, items in sorted(per_doc.items(), key=lambda kv: -len(kv[1])):
        row = [round(sum(item[name] for item in items) / len(items), 4) for name in METRICS]
        lines.append(f"| {doc} | {len(items)} | {row[0]:.3f} | {row[1]:.3f} | {row[2]:.3f} | {row[3]:.3f} |")

    lines += ["", "## 逐条得分", "", "| 用例 | 问题 | 精确度 | 召回率 | 忠实度 | 相关性 |", "| --- | --- | --- | --- | --- | --- |"]
    for item in sorted(valid, key=lambda x: sum(x[name] for name in METRICS)):
        cells = [f"{item[name]:.3f}" for name in METRICS]
        lines.append(f"| {item['id']} | {item['question'][:26]} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")

    weakest = sorted(valid, key=lambda x: x["context_precision"] + x["context_recall"])[:3]
    lines += ["", "## 待改进用例", ""]
    for item in weakest:
        lines.append(
            f"- **{item['id']}** {item['question']}　"
            f"precision={item['context_precision']:.2f} recall={item['context_recall']:.2f} "
            f"faithfulness={item['faithfulness']:.2f}"
        )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"summary": summary, "valid": len(valid), "total": len(scored)}


def main() -> int:
    parser = argparse.ArgumentParser(description="RAGAS 四指标评测")
    parser.add_argument("--stage", choices=["run", "regen", "judge", "all"], default="all")
    parser.add_argument("--from", dest="source", type=Path, default=None,
                        help="regen 复用检索结果；judge 复用已有 run_*.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", nargs="*", default=None)
    parser.add_argument("--kb", type=int, default=18)
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--cases", type=Path, default=CASES_PATH,
                        help="用例集文件（默认 ragas_cases_20.json；全量用 ragas_cases_50.json）")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--tag", default=None, help="结果文件后缀")
    parser.add_argument("--workers", type=int, default=3, help="判定阶段的本地并发线程数")
    parser.add_argument("--judge-model", default=None,
                        help="判定用的模型（默认跟主模型一致；配额紧时可换成 qwen-plus）")
    parser.add_argument("--resume", type=Path, default=None,
                        help="judge 阶段复用已有 scores_*.json，只补算缺失的指标")
    args = parser.parse_args()

    global JUDGE_MODEL
    JUDGE_MODEL = args.judge_model
    # 线程数不能超过 RPM 闸门，否则每轮都在排队，等于白开
    if settings.llm_max_rpm and args.workers > max(1, settings.llm_max_rpm // 10):
        args.workers = max(1, settings.llm_max_rpm // 10)
        print(f"并发线程数收敛到 {args.workers}（受 LLM_MAX_RPM={settings.llm_max_rpm} 限制）", flush=True)
    if JUDGE_MODEL:
        print(f"判定模型：{JUDGE_MODEL}（生成模型仍为 {settings.llm_default_model}）", flush=True)


    cases = load_cases(args.limit, args.ids, args.cases)
    tag = args.tag or datetime.now().strftime("%m%d_%H%M")
    run_path = OUT_DIR / f"run_{tag}.jsonl"
    report_path = OUT_DIR / f"report_{tag}.md"

    if args.stage in {"run", "all"}:
        print(f"用例集：{args.cases.name}（{len(cases)} 条）", flush=True)
    if args.stage in {"run", "all"}:
        print(f"开始跑 {len(cases)} 条用例（精排={'开' if not args.no_rerank else '关'}）→ {run_path.name}", flush=True)
        started = time.perf_counter()
        run_cases(cases, [args.kb], args.user_id, not args.no_rerank, run_path)
        print(f"检索生成阶段耗时 {(time.perf_counter() - started) / 60:.1f} 分钟", flush=True)

    if args.stage == "regen":
        source = args.source or (OUT_DIR / "run_full.jsonl")
        print(f"复用 {source.name} 的检索结果，只重跑生成 → {run_path.name}", flush=True)
        regen_from(source, run_path)

    if args.stage in {"judge", "all"}:
        # judge 阶段可以 --from 指定已有的 run_*.jsonl，避免为了一次补算重跑检索
        run_source = args.source if (args.stage == "judge" and args.source) else run_path
        records = [
            json.loads(line)
            for line in run_source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        records = [item for item in records if item.get("answer")]
        existing: dict[str, dict] = {}
        if args.resume and args.resume.exists():
            previous = json.loads(args.resume.read_text(encoding="utf-8"))
            existing = {item["id"]: item for item in previous}
            reusable = sum(1 for item in existing.values()
                           if all(item.get(name) is not None for name in METRICS))
            print(f"复用 {args.resume.name}：{reusable} 条四指标齐全，只补算缺失部分", flush=True)
        print(f"开始打分 {len(records)} 条（并发 {args.workers}，RPM 上限 {settings.llm_max_rpm}）……", flush=True)
        scored = judge_cases(records, workers=args.workers, existing=existing)
        (OUT_DIR / f"scores_{tag}.json").write_text(
            json.dumps(scored, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary = build_report(
            scored,
            report_path,
            {"kb_ids": [args.kb], "use_rerank": not args.no_rerank, "cases": args.cases.name},
        )
        print("\n===== RAGAS 四指标 =====")
        for name, value in summary["summary"].items():
            print(f"  {name:<20} {value:.4f}")
        print(f"  有效样本 {summary['valid']}/{summary['total']}")
        print(f"\n报告：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
