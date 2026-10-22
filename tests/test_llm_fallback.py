"""模型降级链路：某个模型 403 / 404 时自动换下一个，不再把英文异常抛给用户。"""
from __future__ import annotations

import time

import pytest

from app.core.config import settings
from app.core.exceptions import BizError
from app.services import llm


class _Denied(Exception):
    """模拟 openai 的 PermissionDeniedError（403）。"""

    status_code = 403

    def __init__(self) -> None:
        super().__init__(
            "Error code: 403 - {'error': {'message': 'Access to model denied. "
            "Please make sure you are eligible for using the model.', "
            "'type': 'AccessDenied.Unpurchased'}}"
        )


class _NotFound(Exception):
    status_code = 404

    def __init__(self) -> None:
        super().__init__("Error code: 404 - Model not exist: qwen3.8-x")


class _Timeout(Exception):
    status_code = 504

    def __init__(self) -> None:
        super().__init__("Request timed out")


class _Arrears(Exception):
    """模拟阿里云账户欠费（400 Arrearage）：key 有效、模型有权限，但账户状态不良。"""

    status_code = 400

    def __init__(self) -> None:
        super().__init__(
            "Error code: 400 - {'error': {'message': 'Access denied, please make sure your "
            "account is in good standing. For details, see: .../error-code#overdue-payment', "
            "'type': 'Arrearage', 'code': 'Arrearage'}}"
        )


class _RateLimited(Exception):
    """模拟阿里云每分钟请求数超限（429 limit_requests）——不是欠费。"""

    status_code = 429

    def __init__(self) -> None:
        super().__init__(
            "Error code: 429 - {'error': {'message': 'You have exceeded your current request "
            "limit. For details, see: .../error-code#rate-limit', 'type': 'limit_requests', "
            "'code': 'limit_requests'}}"
        )


class _BadParam(Exception):
    """模拟模型不认 enable_thinking（400 invalid_parameter）。"""

    status_code = 400

    def __init__(self) -> None:
        super().__init__(
            "Error code: 400 - {'error': {'code': 'invalid_parameter', "
            "'message': 'Unsupported parameter: enable_thinking'}}"
        )


def _chunk(text: str):
    class _Delta:
        content = text

    class _Choice:
        delta = _Delta()

    class _Chunk:
        choices = [_Choice()]

    return _Chunk()


class _FakeClient:
    """record 里登记每个模型的行为：'ok' / 'denied' / 'missing' / 'timeout'。"""

    def __init__(self, behaviour: dict[str, str], answer: str = "可用"):
        self.behaviour = behaviour
        self.answer = answer
        self.calls: list[tuple[str, bool]] = []
        self.attempts: dict[str, int] = {}
        self.extra: list[dict] = []

        class _Completions:
            def __init__(self, outer):
                self.outer = outer

            def create(self, *, model, messages, stream=False, **kwargs):
                self.outer.calls.append((model, stream))
                self.outer.extra.append(kwargs.get("extra_body") or {})
                mode = self.outer.behaviour.get(model, "ok")
                if mode == "limited":
                    raise _RateLimited()
                if mode == "bad_param":
                    # 某个模型不认 enable_thinking：带上该参数就 400
                    if kwargs.get("extra_body"):
                        raise _BadParam()
                    mode = "ok"
                if mode == "limited_once":
                    # 第一次限流、第二次放行：验证退避重试能救回来
                    if self.outer.attempts.get(model, 0) == 0:
                        self.outer.attempts[model] = 1
                        raise _RateLimited()
                    mode = "ok"
                if mode == "denied":
                    raise _Denied()
                if mode == "missing":
                    raise _NotFound()
                if mode == "timeout":
                    raise _Timeout()
                if mode == "arrears":
                    raise _Arrears()
                if stream:
                    return iter([_chunk(self.outer.answer[:2]), _chunk(self.outer.answer[2:])])
                return _Completion(self.outer.answer)

        class _Chat:
            def __init__(self, outer):
                self.completions = _Completions(outer)

        self.chat = _Chat(self)


class _Completion:
    def __init__(self, text: str):
        class _Message:
            content = text

        class _Choice:
            message = _Message()

        self.choices = [_Choice()]


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """每个用例都从干净的拉黑表开始，并固定候选顺序。"""
    monkeypatch.setattr(llm, "_blocked_until", {})
    monkeypatch.setattr(llm, "_last_good", None)
    monkeypatch.setattr(settings, "llm_default_model", "qwen3.7-max-preview")
    monkeypatch.setattr(settings, "llm_available_models", "qwen3.7-max-preview,qwen3-vl-plus,qwen-max")
    # 单元测试不排队、不真等退避
    monkeypatch.setattr(settings, "llm_max_rpm", 0)
    monkeypatch.setattr(settings, "llm_rate_retries", 3)
    monkeypatch.setattr(settings, "llm_enable_thinking", False)
    monkeypatch.setattr(llm, "_THINKING_UNSUPPORTED", set())
    monkeypatch.setattr(llm, "_retry_delay", lambda exc, attempt: 0.0)
    llm._limiter.reset()
    yield


def _use(monkeypatch, client: _FakeClient) -> None:
    monkeypatch.setattr(llm, "get_client", lambda: client)


def test_complete_falls_back_to_next_model(monkeypatch):
    client = _FakeClient({"qwen3.7-max-preview": "denied"}, answer="降级成功")
    _use(monkeypatch, client)

    assert llm.complete([{"role": "user", "content": "hi"}]) == "降级成功"
    assert [c[0] for c in client.calls] == ["qwen3.7-max-preview", "qwen3-vl-plus"]


def test_stream_falls_back_before_first_token(monkeypatch):
    client = _FakeClient({"qwen3.7-max-preview": "denied"}, answer="流式降级")
    _use(monkeypatch, client)

    text = "".join(llm.stream_chat([{"role": "user", "content": "hi"}]))
    assert text == "流式降级"
    assert [c[0] for c in client.calls] == ["qwen3.7-max-preview", "qwen3-vl-plus"]


def test_denied_model_is_skipped_within_block_window(monkeypatch):
    client = _FakeClient({"qwen3.7-max-preview": "denied"})
    _use(monkeypatch, client)

    llm.complete([{"role": "user", "content": "hi"}])
    llm.complete([{"role": "user", "content": "hi"}])
    # 第二次不应该再撞已拉黑的模型
    assert [c[0] for c in client.calls] == ["qwen3.7-max-preview", "qwen3-vl-plus", "qwen3-vl-plus"]


def test_last_good_model_goes_first(monkeypatch):
    client = _FakeClient({"qwen3.7-max-preview": "denied"})
    _use(monkeypatch, client)

    llm.complete([{"role": "user", "content": "hi"}])
    assert llm._last_good == "qwen3-vl-plus"
    calls_before = len(client.calls)
    llm.complete([{"role": "user", "content": "hi"}])
    assert client.calls[calls_before][0] == "qwen3-vl-plus"


def test_all_models_denied_raises_friendly_error(monkeypatch):
    client = _FakeClient({m: "denied" for m in ("qwen3.7-max-preview", "qwen3-vl-plus", "qwen-max")})
    _use(monkeypatch, client)

    with pytest.raises(BizError) as excinfo:
        llm.complete([{"role": "user", "content": "hi"}])
    message = excinfo.value.message
    assert "所有候选模型均不可用" in message
    assert "AccessDenied.Unpurchased" in message
    assert "Error code: 403" not in message          # 英文原始异常不能直接甩给用户
    assert excinfo.value.status_code == 503


def test_timeout_is_not_treated_as_model_unavailable(monkeypatch):
    client = _FakeClient({"qwen3.7-max-preview": "timeout"})
    _use(monkeypatch, client)

    with pytest.raises(BizError) as excinfo:
        llm.complete([{"role": "user", "content": "hi"}])
    assert "大模型调用失败" in excinfo.value.message
    assert len(client.calls) == 1                    # 超时不换模型，避免放大故障


def test_arrears_is_reported_as_account_issue(monkeypatch):
    """欠费是账户级故障：换模型没用，不能把 5 个模型都打一遍，提示也要直说欠费。"""
    client = _FakeClient({m: "arrears" for m in ("qwen3.7-max-preview", "qwen3-vl-plus", "qwen-max")})
    _use(monkeypatch, client)

    with pytest.raises(BizError) as excinfo:
        llm.complete([{"role": "user", "content": "hi"}])
    assert len(client.calls) == 1                    # 账户级故障不放大流量
    message = excinfo.value.message
    assert "欠费" in message and "Arrearage" in message
    assert "免费额度" in message                      # 说清「有额度也调不通」的原因


def test_thinking_is_disabled_for_qwen3(monkeypatch):
    """qwen3 默认开深度思考，必须显式下发 enable_thinking=false，否则响应慢几倍。"""
    client = _FakeClient({})
    _use(monkeypatch, client)

    llm.complete([{"role": "user", "content": "hi"}])
    assert client.extra[0] == {"enable_thinking": False}


def test_thinking_param_skipped_for_non_qwen3(monkeypatch):
    """qwen-max 这类老模型不认这个参数，传了会 400，必须不发。"""
    monkeypatch.setattr(settings, "llm_default_model", "qwen-max")
    monkeypatch.setattr(settings, "llm_available_models", "qwen-max")
    client = _FakeClient({})
    _use(monkeypatch, client)

    llm.complete([{"role": "user", "content": "hi"}])
    assert client.extra[0] == {}


def test_thinking_param_dropped_when_model_rejects_it(monkeypatch):
    """模型不认 enable_thinking 时去掉参数重试，并记住不再发。"""
    client = _FakeClient({"qwen3.7-max-preview": "bad_param"}, answer="去掉参数后可用")
    _use(monkeypatch, client)
    monkeypatch.setattr(llm, "_THINKING_UNSUPPORTED", set())

    assert llm.complete([{"role": "user", "content": "hi"}]) == "去掉参数后可用"
    assert len(client.calls) == 2
    assert client.extra[1] == {}
    assert "qwen3.7-max-preview" in llm._THINKING_UNSUPPORTED


def test_rate_limit_is_retried_not_treated_as_denied(monkeypatch):
    """429 limit_requests 是 RPM 超限，等一下就过：同一模型退避重试，不要换模型。"""
    client = _FakeClient({"qwen3.7-max-preview": "limited_once"}, answer="重试成功")
    _use(monkeypatch, client)

    assert llm.complete([{"role": "user", "content": "hi"}]) == "重试成功"
    assert [c[0] for c in client.calls] == ["qwen3.7-max-preview", "qwen3.7-max-preview"]
    assert llm._blocked_until == {}                    # 限流不拉黑模型


def test_rate_limit_exhausted_reports_quota_not_arrears(monkeypatch):
    """重试次数用完仍 429：提示要说「频率超限」并给出 LLM_MAX_RPM，不能说成欠费。"""
    client = _FakeClient({m: "limited" for m in ("qwen3.7-max-preview", "qwen3-vl-plus", "qwen-max")})
    _use(monkeypatch, client)

    with pytest.raises(BizError) as excinfo:
        llm.complete([{"role": "user", "content": "hi"}])
    message = excinfo.value.message
    assert "请求频率超限" in message and "LLM_MAX_RPM" in message
    assert "欠费" not in message
    assert "Error code: 429" not in message
    assert len(client.calls) == settings.llm_rate_retries    # 只打一个模型，重试用尽就停


def test_rate_limiter_spaces_requests(monkeypatch):
    """LLM_MAX_RPM=600 时相邻两次请求至少隔 0.1s，把并发摊平成节奏。"""
    monkeypatch.setattr(settings, "llm_max_rpm", 600)
    llm._limiter.reset()

    started = time.monotonic()
    for _ in range(3):
        llm._limiter.acquire()
    assert time.monotonic() - started >= 0.2


def test_probe_not_fooled_by_thinking_param(monkeypatch):
    """自检时模型不认 enable_thinking，不能把「参数不支持」当成「模型不可用」。"""
    client = _FakeClient({"qwen3.7-max-preview": "bad_param"})
    _use(monkeypatch, client)
    monkeypatch.setattr(llm, "_probe_cache", {"ts": 0.0, "result": None})

    state = {item["model"]: item["ok"] for item in llm.probe_models(force=True)["candidates"]}
    assert state["qwen3.7-max-preview"] is True


def test_probe_reports_each_candidate(monkeypatch):
    client = _FakeClient({"qwen3.7-max-preview": "denied", "qwen3-vl-plus": "missing"})
    _use(monkeypatch, client)
    monkeypatch.setattr(llm, "_probe_cache", {"ts": 0.0, "result": None})

    snapshot = llm.probe_models(force=True)
    state = {item["model"]: item["ok"] for item in snapshot["candidates"]}
    assert state["qwen3.7-max-preview"] is False
    assert state["qwen3-vl-plus"] is False
    assert state["qwen-max"] is True
    assert snapshot["any_available"] is True
    assert snapshot["active_model"] == "qwen-max"
