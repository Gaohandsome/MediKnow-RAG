"""大模型可用性自检：逐个试探候选模型，查欠费 / 未授权 / key 不匹配。

用法：
    python scripts/bench/check_llm.py                              # 用 .env 现有配置，60 秒缓存
    python scripts/bench/check_llm.py --force                      # 立即重新探测
    python scripts/bench/check_llm.py --key sk-xxx                 # 临时换一把 key 试，不写 .env
    python scripts/bench/check_llm.py --key sk-xxx \
        --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
        --model qwen3.7-max-preview --model qwen-plus        # 临时换端点与模型
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.services import llm  # noqa: E402


def _apply_overrides(args: argparse.Namespace) -> None:
    """临时覆盖配置，只影响本次进程，不落盘。"""
    if args.key:
        settings.llm_api_key = args.key
    if args.base_url:
        settings.llm_base_url = args.base_url
    if args.model:
        settings.llm_available_models = ",".join(args.model)
        if settings.llm_default_model not in args.model:
            settings.llm_default_model = args.model[0]
    # get_client 带 lru_cache，换了配置必须清掉
    llm.get_client.cache_clear()
    llm._blocked_until.clear()
    llm._last_good = None
    llm._probe_cache.update({"ts": 0.0, "result": None})


def main() -> int:
    parser = argparse.ArgumentParser(description="大模型可用性自检")
    parser.add_argument("--force", action="store_true", help="跳过缓存立即探测")
    parser.add_argument("--key", help="临时使用的 API Key（不写入 .env）")
    parser.add_argument("--base-url", dest="base_url", help="临时使用的 Base URL")
    parser.add_argument("--model", action="append", help="临时指定候选模型，可重复")
    args = parser.parse_args()

    _apply_overrides(args)
    snapshot = llm.probe_models(force=True)

    print(f"网关      : {snapshot['base_url']}")
    print(f"密钥尾部  : ...{settings.llm_api_key[-6:]}")
    print(f"默认模型  : {snapshot['default_model']}")
    print(f"实际在用  : {snapshot['active_model']}")
    print(f"探测时间  : {snapshot['checked_at']}\n")

    for item in snapshot["candidates"]:
        mark = "✓" if item["ok"] else "✗"
        detail = "" if item["ok"] else f"  {item['detail']}"
        print(f"  {mark} {item['model']}{detail}")

    if snapshot["any_available"]:
        print("\n结论：至少一个模型可用，问答功能正常。")
        return 0

    arrears = [i for i in snapshot["candidates"] if "Arrearage" in i["detail"] or "账户欠费" in i["detail"]]
    if len(arrears) == len(snapshot["candidates"]):
        print(
            "\n结论：key 有效、模型也有权限，但全部返回 Arrearage（账户欠费 / 状态异常）。\n"
            "  欠费状态下阿里云的免费额度一样会被冻结，所以「控制台显示还有额度」和「调不通」并不矛盾。\n"
            "  处理：登录阿里云 → 费用中心，结清欠款 / 补全实名认证，然后用同一条命令复测：\n"
            "    python scripts/bench/check_llm.py --force"
        )
        return 1

    denied = [i for i in snapshot["candidates"] if "Unpurchased" in i["detail"] or "AccessDenied" in i["detail"]]
    if len(denied) == len(snapshot["candidates"]):
        print(
            "\n结论：全部候选都是 AccessDenied.Unpurchased —— 这是 key / 账户级问题，不是单个模型没额度。\n"
            "  常见原因：这把 key 与控制台里看到免费额度的账户不是同一个（网关密钥 vs 百炼密钥）。\n"
            "  换一把控制台里的 API-KEY 再试：\n"
            "    python scripts/bench/check_llm.py --key sk-xxxxxxxx \\\n"
            "        --base-url https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    else:
        print("\n结论：没有可用模型，请按上面的原因逐条排查。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
