"""容量测算：单机 CPU 上 bge-m3 / bge-reranker 的延迟与并发退化。

用途：回答「这台机器能同时撑多少人问答」。只读，不改任何数据。

用法：
    .venv/Scripts/python.exe scripts/bench/capacity_probe.py
    .venv/Scripts/python.exe scripts/bench/capacity_probe.py --concurrency 1,4,8,16
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

QUERY = "患者使用抗生素前需要做哪些评估，皮试阴性的处理流程是什么"
# 模拟召回候选项：真实父块约 650~950 字
PASSAGE = (
    "抗菌药物使用前评估流程：一、明确用药指征，结合患者症状、体征、实验室检查与影像学结果，"
    "判断是否存在细菌感染证据；二、询问过敏史，重点记录青霉素类、头孢菌素类药物过敏史及严重程度；"
    "三、评估肝肾功能，按肌酐清除率调整剂量；四、留取病原学标本，在使用抗菌药物前完成血培养、"
    "痰培养等检查；五、皮试管理，青霉素类药物使用前须做皮试，皮试阴性方可使用，皮试阳性者禁用并"
    "在病历首页标注；六、用药后 48~72 小时评价疗效，无效者需重新评估病原学与感染灶。"
) * 3


def _timed(fn, rounds: int = 1) -> list[float]:
    costs = []
    for _ in range(rounds):
        start = time.perf_counter()
        fn()
        costs.append((time.perf_counter() - start) * 1000)
    return costs


def _summary(name: str, costs: list[float]) -> str:
    costs = sorted(costs)
    p50 = statistics.median(costs)
    p95 = costs[max(0, int(len(costs) * 0.95) - 1)]
    return f"{name:22s} n={len(costs):3d}  p50={p50:7.1f}ms  p95={p95:7.1f}ms  max={costs[-1]:7.1f}ms"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", default="1,4,8,16")
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--passages", type=int, default=20)
    args = parser.parse_args()
    levels = [int(item) for item in args.concurrency.split(",") if item.strip()]

    from app.services.embedding import get_embedder
    from app.services.reranker import get_reranker

    print("加载模型 ...", flush=True)
    started = time.perf_counter()
    embedder = get_embedder()
    reranker = get_reranker()
    embedder.encode([QUERY])
    print(f"加载完成，耗时 {time.perf_counter() - started:.1f}s\n", flush=True)

    print("=== 单条 query 向量化（bge-m3, cpu） ===")
    for level in levels:
        def one() -> None:
            embedder.encode([QUERY])
        with ThreadPoolExecutor(max_workers=level) as pool:
            costs = list(pool.map(lambda _: _timed(one)[0], range(level * args.rounds)))
        throughput = 1000 / (statistics.mean(costs) / level)
        print(_summary(f"并发 {level}", costs) + f"  理论吞吐={throughput:5.1f} q/s")

    print("\n=== 精排 20 个父块（bge-reranker, cpu） ===")
    passages = [PASSAGE] * args.passages
    for level in levels:
        if level > 8:
            continue
        def one_rank() -> None:
            reranker.score(QUERY, passages)
        with ThreadPoolExecutor(max_workers=level) as pool:
            costs = list(pool.map(lambda _: _timed(one_rank)[0], range(level * 2)))
        throughput = 1000 / (statistics.mean(costs) / level)
        print(_summary(f"并发 {level}", costs) + f"  理论吞吐={throughput:5.2f} 次/s")


if __name__ == "__main__":
    main()
