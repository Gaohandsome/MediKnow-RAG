"""大模型客户端（通义千问，OpenAI 兼容协议）。

一个模型 403（未授权 / 未购买 / 已下线）不再直接抛给用户：
按 `LLM_AVAILABLE_MODELS` 的顺序自动换下一个，并把失败的模型拉黑 5 分钟，
避免每个请求都去撞一次必然失败的模型。

429（`limit_requests`，每分钟请求数超限）与欠费是两件事：
- 欠费（400 Arrearage / overdue-payment）→ 换模型没用，直接告诉用户去结清欠款；
- 限流（429）→ 请求本身没问题，等一会儿就能过，所以先按 `LLM_MAX_RPM`
  在本地排队（令牌间隔），撞上了再指数退避重试，不把整批判定浪费掉。
"""
from __future__ import annotations

import random
import threading
import time
from collections.abc import Iterator
from functools import lru_cache

from loguru import logger
from openai import OpenAI

from app.core.config import settings
from app.core.exceptions import BizError

# 撞到「未授权/不存在」的模型，这么多秒内不再尝试
_BLOCK_SECONDS = 300.0
# 探测结果缓存，避免 /system/llm-status 被刷
_PROBE_TTL = 60.0

_blocked_until: dict[str, float] = {}
_lock = threading.Lock()
_last_good: str | None = None
_probe_cache: dict[str, object] = {"ts": 0.0, "result": None}

# 这些字样表示「这个模型当前用不了」，可以换下一个；超时/限流不在此列
_UNAVAILABLE_HINTS = (
    "AccessDenied",
    "Unpurchased",
    "does not have access",
    "does not exist",
    "Model not exist",
    "model_not_found",
    "invalid_model",
    "Unsupported model",
)


@lru_cache
def get_client() -> OpenAI:
    if not settings.llm_api_key:
        raise BizError("未配置大模型 API Key，请在 .env 中设置 LLM_API_KEY", status_code=500)
    # max_retries=0：429 的重试统一由 `_request` 做，才能按 LLM_MAX_RPM 排队、
    # 打出可读日志，也避免 SDK 自带重试与本项目退避叠成两层。
    return OpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
        max_retries=0,
    )


# ---------------------------------------------------------------- 限流 / 退避


class _RateLimiter:
    """按最小间隔发请求，把「每分钟 N 次」摊平成稳定节奏。

    同时在跑的线程会依次排队，等效于一个全局的 RPM 闸门；`LLM_MAX_RPM<=0` 时直接放行。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_at = 0.0

    def acquire(self) -> None:
        rpm = int(settings.llm_max_rpm or 0)
        if rpm <= 0:
            return
        interval = 60.0 / rpm
        with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                if wait > 5:
                    logger.debug(f"限流排队 {wait:.1f}s（LLM_MAX_RPM={rpm}）")
                time.sleep(wait)
                now = time.monotonic()
            self._next_at = now + interval

    def reset(self) -> None:
        with self._lock:
            self._next_at = 0.0


_limiter = _RateLimiter()

# ---------------------------------------------------------------- 深度思考开关
#
# qwen3 系列默认 `enable_thinking=true`：先吐几百上千 token 的推理再给答案，
# 首字延迟和总耗时都成倍增加。RAG 的回答基本是「照资料归纳」，用不上这层推理，
# 所以默认关掉（`LLM_ENABLE_THINKING=false`）。
#
# 两个边界：
# 1. 只有 qwen3* 支持这个参数，qwen-max / qwen-plus / qwen-vl-ocr 传了会 400，必须跳过；
# 2. 万一某个模型不认这个参数，`_call_model` 会去掉重试一次，并把这个模型记进黑名单。

_THINKING_UNSUPPORTED: set[str] = set()


def thinking_kwargs(model: str) -> dict:
    """返回要合并进请求的思考开关参数；不需要时返回空 dict。"""
    if settings.llm_enable_thinking or not model:
        return {}
    if not model.lower().startswith("qwen3") or model in _THINKING_UNSUPPORTED:
        return {}
    return {"extra_body": {"enable_thinking": False}}


def _is_unsupported_param(exc: BaseException) -> bool:
    """400/422 且指向参数不支持——此时去掉 extra_body 重试即可。"""
    status = getattr(exc, "status_code", None)
    text = str(exc)
    if status not in (400, 422) and "invalid_parameter" not in text:
        return False
    return "enable_thinking" in text or "invalid_parameter" in text or "Unsupported parameter" in text


def _call_model(model: str, build):
    """带思考开关地发一次请求：参数被拒时自动去掉重试，其余异常原样抛出。

    `build(extra)` 直接发请求（内部自己调 SDK），`extra` 是要合并的参数。
    """
    extra = thinking_kwargs(model)
    try:
        return _request(model, lambda: build(extra))
    except Exception as exc:  # noqa: BLE001
        if extra and _is_unsupported_param(exc):
            logger.warning(f"{model} 不支持 enable_thinking，去掉该参数重试：{str(exc)[:120]}")
            _THINKING_UNSUPPORTED.add(model)
            return _request(model, lambda: build({}))
        raise


# 429 / 限流类错误：等一等就能过，不该换模型也不该判死
_RATE_HINTS = (
    "limit_requests",
    "Requests rate limit exceeded",
    "Throttling.RateQuota",
    "Throttling",
    "rate limit",
)


def _is_rate_limited(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    text = str(exc)
    return any(hint in text for hint in _RATE_HINTS)


def _retry_delay(exc: BaseException, attempt: int) -> float:
    """优先听服务端给的 Retry-After，没给就 1/2/4/8 秒加抖动。"""
    retry_after = None
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        try:
            retry_after = float(headers.get("retry-after"))
        except (TypeError, ValueError):
            retry_after = None
    if retry_after is not None:
        return min(max(retry_after, 0.5), 30.0)
    return min(2.0**attempt, 20.0) + random.uniform(0, 0.5)


def _request(model: str, open_it) -> object:
    """发一次请求，429 时退避重试；其余异常原样抛出（交给上层判是否换模型）。

    `open_it` 是个无参函数，返回 SDK 的响应 / 流对象——这样非流式和流式共用一套重试。
    """
    attempts = max(1, int(settings.llm_rate_retries or 1))
    for attempt in range(attempts):
        _limiter.acquire()
        try:
            return open_it()
        except Exception as exc:  # noqa: BLE001
            if not _is_rate_limited(exc) or attempt == attempts - 1:
                raise
            delay = _retry_delay(exc, attempt)
            logger.warning(
                f"模型限流（429），{delay:.1f}s 后重试第 {attempt + 1}/{attempts - 1} 次：{model}"
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------- 模型降级


def _is_unavailable(exc: BaseException) -> bool:
    """判断异常是否属于「换个模型就能解决」。"""
    status = getattr(exc, "status_code", None)
    if status in (403, 404):
        return True
    if status == 401:  # 密钥本身无效，换模型没用
        return False
    text = str(exc)
    return any(hint in text for hint in _UNAVAILABLE_HINTS)


def _model_order(preferred: str | None) -> list[str]:
    """候选顺序：指定模型 → 默认模型 → 其余可用模型（含上次成功过的）。"""
    order: list[str] = []
    for name in ([preferred] if preferred else []) + [settings.llm_default_model, *settings.available_models]:
        if name and name not in order:
            order.append(name)
    with _lock:
        if _last_good and _last_good in order:
            order.remove(_last_good)
            order.insert(0, _last_good)
    return order


def _candidates(preferred: str | None) -> list[str]:
    order = _model_order(preferred)
    with _lock:
        now = time.monotonic()
        alive = [name for name in order if _blocked_until.get(name, 0.0) <= now]
    # 全被拉黑了也要试一次，否则额度恢复后会一直判死
    return alive or order


def _mark(model: str, ok: bool) -> None:
    global _last_good
    with _lock:
        if ok:
            _last_good = model
            _blocked_until.pop(model, None)
        else:
            _blocked_until[model] = time.monotonic() + _BLOCK_SECONDS


_ARREARS_HINTS = ("Arrearage", "overdue-payment", "account is in good standing", "欠费")


def _is_arrears(exc: BaseException) -> bool:
    """账户欠费：key 有效、模型有权限，但账户状态不良被拦。换模型没用。"""
    text = str(exc)
    return any(hint in text for hint in _ARREARS_HINTS)


def _friendly(exc: BaseException, model: str) -> str:
    """把 SDK 的英文异常翻译成用户能看懂的话。"""
    text = str(exc)
    if _is_rate_limited(exc):
        return (
            f"模型「{model}」请求频率超限（429 limit_requests）：该模型的每分钟请求数已达上限，"
            f"退避重试后仍未成功。请把 .env 里的 LLM_MAX_RPM 调小（当前 {settings.llm_max_rpm}）、"
            f"降低并发，或等一两分钟再试。"
        )
    if _is_arrears(exc):
        return (
            f"模型「{model}」调用被拒：阿里云账户欠费或状态异常（Arrearage）。"
            f"欠费状态下免费额度同样被冻结，请到阿里云「费用中心」结清欠款后重试。"
        )
    if "AccessDenied" in text or "Unpurchased" in text or "does not have access" in text:
        return (
            f"模型「{model}」未授权或额度不足（AccessDenied.Unpurchased）。"
            f"请确认该模型已开通，或在 .env 中把 LLM_DEFAULT_MODEL 换成可用的模型。"
        )
    if "Incorrect API key" in text or "invalid_api_key" in text or "401" in text:
        return "大模型 API Key 无效，请检查 .env 中的 LLM_API_KEY"
    return f"大模型调用失败：{text}"


def _all_failed(failures: list[tuple[str, BaseException]]) -> str:
    names = "、".join(name for name, _ in failures) or "（未配置候选模型）"
    if failures and all(_is_arrears(exc) for _, exc in failures):
        tail = "，原因均为阿里云账户欠费（Arrearage）—— 欠费状态下免费额度也被冻结，请到费用中心结清欠款"
    elif failures and all(_is_denied(exc) for _, exc in failures):
        tail = "，原因均为未授权/额度不足（AccessDenied.Unpurchased）"
    elif failures and all(_is_rate_limited(exc) for _, exc in failures):
        tail = (
            f"，原因均为请求频率超限（429 limit_requests）—— 请调小 LLM_MAX_RPM（当前 {settings.llm_max_rpm}）"
            "或降低并发后重试"
        )
    else:
        tail = ""
    return f"所有候选模型均不可用：{names}{tail}。请检查账户额度，或在 .env 里换一个已开通的模型。"


def _is_denied(exc: BaseException) -> bool:
    text = str(exc)
    return "AccessDenied" in text or "Unpurchased" in text


# ---------------------------------------------------------------- 对外接口


def complete(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 800,
) -> str:
    """非流式调用，用于查询理解、意图识别这类短输出任务。带模型降级。"""
    client = get_client()
    failures: list[tuple[str, BaseException]] = []
    for name in _candidates(model):
        def _open(extra, name: str = name):
            return client.chat.completions.create(
                model=name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
                **extra,
            )

        try:
            response = _call_model(name, _open)
        except Exception as exc:  # noqa: BLE001
            if _is_unavailable(exc):
                _mark(name, False)
                failures.append((name, exc))
                logger.warning(f"模型不可用，换下一个：{name} -> {str(exc)[:120]}")
                continue
            logger.exception(f"大模型调用失败：{exc}")
            raise BizError(_friendly(exc, name), status_code=502) from exc
        _mark(name, True)
        if not response.choices:
            return ""
        return (response.choices[0].message.content or "").strip()
    raise BizError(_all_failed(failures), status_code=503)


def _chain(first, rest: Iterator):
    if first is not None:
        yield first
    yield from rest


def stream_chat(
    messages: list[dict],
    model: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """流式调用大模型，逐段产出文本增量。首个 chunk 之前的失败会自动换模型。"""
    client = get_client()
    payload = {
        "messages": messages,
        "stream": True,
        "temperature": settings.llm_temperature if temperature is None else temperature,
        "top_p": settings.llm_top_p if top_p is None else top_p,
        "max_tokens": settings.llm_max_tokens if max_tokens is None else max_tokens,
    }
    failures: list[tuple[str, BaseException]] = []
    for name in _candidates(model):
        logger.info(
            f"调用大模型：model={name} temperature={payload['temperature']} "
            f"max_tokens={payload['max_tokens']}"
        )
        try:
            def _open_stream(extra, name: str = name):
                stream = client.chat.completions.create(model=name, **payload, **extra)
                iterator = iter(stream)
                # 真正发起请求：403 / 404 / 429 在这里抛出，此时还没有吐任何字
                return iterator, next(iterator, None)

            iterator, first = _call_model(name, _open_stream)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            if _is_unavailable(exc):
                _mark(name, False)
                failures.append((name, exc))
                logger.warning(f"模型不可用，换下一个：{name} -> {str(exc)[:120]}")
                continue
            logger.exception(f"大模型调用失败：{exc}")
            raise BizError(_friendly(exc, name), status_code=502) from exc

        _mark(name, True)
        try:
            for chunk in _chain(first, iterator):
                if not chunk.choices:
                    continue
                content = getattr(chunk.choices[0].delta, "content", None)
                if content:
                    yield content
        except Exception as exc:  # noqa: BLE001
            # 已经开始吐字了，不能重试，只能报错
            logger.exception(f"大模型流式输出中断：{exc}")
            raise BizError(_friendly(exc, name), status_code=502) from exc
        return
    raise BizError(_all_failed(failures), status_code=503)


def chat_once(messages: list[dict], model: str | None = None, max_tokens: int = 64) -> str:
    """非流式调用，用于生成会话标题等轻量场景。"""
    return complete(messages, model=model, temperature=0.3, max_tokens=max_tokens)


# ---------------------------------------------------------------- 诊断


def probe_models(force: bool = False) -> dict:
    """逐个试探候选模型能否调用（max_tokens=1），用于排查欠费 / 未授权。

    结果缓存 `_PROBE_TTL` 秒，避免被反复刷。
    """
    now = time.monotonic()
    cached = _probe_cache.get("result")
    if cached and not force and now - float(_probe_cache.get("ts") or 0) < _PROBE_TTL:
        return cached  # type: ignore[return-value]

    client = get_client()
    results = []
    # 自检要覆盖全部候选，不能被「拉黑 5 分钟」挡住，否则刚充值也看不到恢复
    for name in _model_order(None):
        try:
            # 走 _call_model：模型不认 enable_thinking 时会自动去掉参数重试，
            # 否则会把「参数不支持」误报成「模型不可用」
            _call_model(
                name,
                lambda extra, name=name: client.chat.completions.create(
                    model=name,
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=1,
                    **extra,
                ),
            )
            _mark(name, True)
            results.append({"model": name, "ok": True, "detail": "可用"})
        except Exception as exc:  # noqa: BLE001
            if _is_unavailable(exc):
                _mark(name, False)
            results.append({"model": name, "ok": False, "detail": _friendly(exc, name)})

    snapshot = {
        "default_model": settings.llm_default_model,
        "active_model": _last_good or settings.llm_default_model,
        "base_url": settings.llm_base_url,
        "candidates": results,
        "any_available": any(item["ok"] for item in results),
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _probe_cache["ts"] = now
    _probe_cache["result"] = snapshot
    return snapshot
