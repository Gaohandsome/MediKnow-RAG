"""对比「深度思考」开/关的响应耗时，验证关掉之后到底快多少。

用法：
    python scripts/bench/bench_thinking.py                 # 默认每档 2 次
    python scripts/bench/bench_thinking.py --runs 3 --model qwen3.7-max-preview

只看两个数：首字延迟（用户点了发送到看见第一个字）和总耗时。
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.services.llm import stream_chat  # noqa: E402

SYSTEM = (
    "你是医院知识库问答助手。只依据下面提供的资料回答，资料里没有的内容不要编造，"
    "不确定就说明「资料未明确」。回答分点、给具体数值。"
)
CONTEXT = (
    "【资料 1｜急诊科-成人心肺复苏与除颤操作规范.md】\n"
    "成人心肺复苏：按压部位为胸骨下半部（两乳头连线中点），按压深度 5~6 cm，"
    "频率 100~120 次/分，按压与通气比 30:2；建立高级气道后持续按压 100~120 次/分，"
    "每 6 秒通气 1 次。室颤首次除颤双相波 120~200 J，单相波 360 J，"
    "放电后立即恢复胸外按压，2 分钟后再次评估心律。肾上腺素 1 mg 静脉推注，每 3~5 分钟重复一次。"
)
QUESTION = "成人心肺复苏的按压深度和频率是多少？室颤第一次除颤用多大能量？放完电之后要做什么？"


def one_round(model: str | None) -> tuple[float | None, float]:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"{CONTEXT}\n\n【问题】{QUESTION}"},
    ]
    started = time.perf_counter()
    first_at: float | None = None
    chars = 0
    for chunk in stream_chat(messages, model=model, temperature=0.1, max_tokens=900):
        if first_at is None:
            first_at = time.perf_counter() - started
        chars += len(chunk)
    total = time.perf_counter() - started
    if chars == 0:
        raise RuntimeError("没有收到任何内容")
    return first_at, total


def main() -> int:
    parser = argparse.ArgumentParser(description="深度思考开/关耗时对比")
    parser.add_argument("--runs", type=int, default=2, help="每档跑几次")
    parser.add_argument("--model", default=None, help="默认用 LLM_DEFAULT_MODEL")
    args = parser.parse_args()

    model = args.model or settings.llm_default_model
    print(f"模型：{model}　每档 {args.runs} 次\n")
    result: dict[bool, list[tuple[float | None, float]]] = {}
    for flag in (False, True):
        settings.llm_enable_thinking = flag
        label = "开（先推理）" if flag else "关（直接答）"
        samples = []
        for index in range(args.runs):
            first, total = one_round(model)
            samples.append((first, total))
            print(f"  [{label}] 第 {index + 1} 次：首字 {first:.2f}s　总耗时 {total:.2f}s", flush=True)
        result[flag] = samples

    def avg(values: list[tuple[float | None, float]]) -> tuple[float, float]:
        firsts = [v[0] for v in values if v[0] is not None] or [0.0]
        return statistics.mean(firsts), statistics.mean(v[1] for v in values)

    off_first, off_total = avg(result[False])
    on_first, on_total = avg(result[True])
    print("\n===== 结论 =====")
    print(f"  关闭深度思考：首字 {off_first:.2f}s　总耗时 {off_total:.2f}s")
    print(f"  开启深度思考：首字 {on_first:.2f}s　总耗时 {on_total:.2f}s")
    if on_total and off_total:
        print(f"  关闭后总耗时缩短 {(1 - off_total / on_total) * 100:.0f}%，"
              f"首字提前 {(on_first - off_first):.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
