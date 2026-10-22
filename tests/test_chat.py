"""会话管理与流式问答测试（医疗院内知识库场景）。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import chat_service
from tests.conftest import API

QUESTION = "社区获得性肺炎的门诊经验性抗菌治疗首选什么药物？"


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block.startswith("data:"):
            continue
        events.append(json.loads(block[5:].strip()))
    return events


def _stream(client: TestClient, headers: dict, payload: dict) -> list[dict]:
    response = client.post(f"{API}/chat/stream", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return _parse_sse(response.text)


@pytest.fixture()
def fake_llm(monkeypatch):
    """用固定的假回答替换大模型，便于断言流式链路。"""
    captured = {"calls": []}

    def fake_stream(messages, model=None, temperature=None, top_p=None, max_tokens=None):
        captured["calls"].append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
            }
        )
        for piece in ["根据院内规范，", "门诊无基础疾病患者首选阿莫西林 500 mg 口服", "。" ]:
            yield piece

    monkeypatch.setattr(chat_service, "stream_chat", fake_stream)
    return captured


@pytest.fixture()
def allow_chat_without_kb(monkeypatch):
    """临时关闭"无资料即拒答"，用于验证历史轮数等链路逻辑。"""
    monkeypatch.setattr(settings, "safety_refuse_when_no_context", False)


def test_session_crud(client: TestClient, new_user: dict):
    created = client.post(
        f"{API}/chat/sessions", headers=new_user["headers"], json={"name": "测试会话", "kb_ids": []}
    )
    assert created.status_code == 200
    session = created.json()["data"]

    listing = client.get(f"{API}/chat/sessions", headers=new_user["headers"]).json()["data"]
    assert any(item["id"] == session["id"] for item in listing)

    renamed = client.patch(
        f"{API}/chat/sessions/{session['id']}", headers=new_user["headers"], json={"name": "新名字"}
    )
    assert renamed.json()["data"]["name"] == "新名字"

    messages = client.get(f"{API}/chat/sessions/{session['id']}/messages", headers=new_user["headers"])
    assert messages.json()["data"] == []

    assert client.delete(f"{API}/chat/sessions/{session['id']}", headers=new_user["headers"]).status_code == 200
    assert client.get(f"{API}/chat/sessions/{session['id']}/messages", headers=new_user["headers"]).status_code == 404


def test_models_endpoint(client: TestClient, new_user: dict):
    response = client.get(f"{API}/chat/models", headers=new_user["headers"])
    data = response.json()["data"]
    assert data["default_model"]
    assert data["models"]
    assert "temperature" in data["defaults"]


def test_safety_config_endpoint(client: TestClient):
    """安全配置接口向前端提供免责声明文案。"""
    response = client.get(f"{API}/system/safety-config")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "不能替代执业医师" in data["disclaimer"]
    assert data["disclaimer_enabled"] is True


def test_stream_refuses_without_knowledge_base(client: TestClient, new_user: dict, fake_llm):
    """严格模式：未选择知识库时拒答，且不得调用大模型。"""
    events = _stream(client, new_user["headers"], {"question": QUESTION, "kb_ids": []})

    types = [event["type"] for event in events]
    assert "safety" in types and "done" in types
    safety = next(event for event in events if event["type"] == "safety")
    assert safety["refusal"] is True
    assert safety["reason"] == "no_kb"
    assert "不能替代执业医师" in safety["disclaimer"]

    answer = "".join(event.get("content", "") for event in events if event["type"] == "delta")
    assert "尚未选择知识库" in answer
    assert fake_llm["calls"] == [], "拒答时不应调用大模型"

    done = next(event for event in events if event["type"] == "done")
    assert done["refused"] is True


def test_stream_answer_without_knowledge_base_when_refusal_disabled(
    client: TestClient, new_user: dict, fake_llm, allow_chat_without_kb
):
    events = _stream(
        client,
        new_user["headers"],
        {"question": QUESTION, "kb_ids": [], "temperature": 0.5, "max_tokens": 256},
    )

    answer = "".join(event.get("content", "") for event in events if event["type"] == "delta")
    assert answer == "根据院内规范，门诊无基础疾病患者首选阿莫西林 500 mg 口服。"

    call = fake_llm["calls"][0]
    assert call["temperature"] == 0.5
    assert call["max_tokens"] == 256
    assert call["messages"][0]["role"] == "system"
    assert "院内知识库智能问答助手" in call["messages"][0]["content"]

    session_id = events[0]["session_id"]
    messages = client.get(f"{API}/chat/sessions/{session_id}/messages", headers=new_user["headers"]).json()["data"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[1]["content"] == answer


def test_stream_refuses_when_kb_has_no_document(client: TestClient, new_user: dict, knowledge_base: dict, fake_llm):
    """已选知识库但库内无文档：触发无依据拒答。"""
    events = _stream(
        client, new_user["headers"], {"question": QUESTION, "kb_ids": [knowledge_base["id"]]}
    )
    safety = next(event for event in events if event["type"] == "safety")
    assert safety["refusal"] is True
    assert safety["reason"] == "empty"
    assert fake_llm["calls"] == []

    answer = "".join(event.get("content", "") for event in events if event["type"] == "delta")
    assert "未收录" in answer


def test_stream_answer_with_context(client: TestClient, new_user: dict, knowledge_base: dict, fake_llm):
    content = (
        "# 社区获得性肺炎诊疗规范\n\n"
        "门诊、无基础疾病患者：阿莫西林 500 mg 口服，每 8 小时一次。\n"
        "住院非重症患者：头孢曲松 1 g 静脉滴注，每日一次。"
    ).encode("utf-8")
    upload = client.post(
        f"{API}/knowledge-bases/{knowledge_base['id']}/documents",
        headers=new_user["headers"],
        files={"file": ("肺炎诊疗规范.md", content, "text/markdown")},
        data={"chunk_size": "200", "chunk_overlap": "20", "retrieval_mode": "hybrid"},
    )
    assert upload.status_code == 200
    doc_id = upload.json()["data"]["id"]

    import time

    for _ in range(120):
        detail = client.get(f"{API}/documents/{doc_id}", headers=new_user["headers"]).json()["data"]
        if detail["status"] in {"completed", "failed"}:
            break
        time.sleep(0.5)
    assert detail["status"] == "completed"

    events = _stream(
        client,
        new_user["headers"],
        {"question": QUESTION, "kb_ids": [knowledge_base["id"]], "use_rerank": False, "top_k": 3},
    )
    contexts_event = next(event for event in events if event["type"] == "contexts")
    assert contexts_event["contexts"], "应检索到资料"
    assert any("阿莫西林" in item["content"] for item in contexts_event["contexts"])

    safety = next(event for event in events if event["type"] == "safety")
    assert safety["refusal"] is False

    prompt = fake_llm["calls"][0]["messages"]
    assert "参考资料 1" in prompt[-1]["content"]
    assert "阿莫西林" in prompt[-1]["content"]
    assert "院内知识库中暂未收录该内容" in prompt[0]["content"]

    # 同一知识库内的库外问题：相关度不足应拒答，且不再次调用大模型
    calls_before = len(fake_llm["calls"])
    events2 = _stream(
        client,
        new_user["headers"],
        {
            "question": "今天北京的天气怎么样？",
            "session_id": events[0]["session_id"],
            "kb_ids": [knowledge_base["id"]],
            "use_rerank": False,
        },
    )
    safety2 = next(event for event in events2 if event["type"] == "safety")
    assert safety2["refusal"] is True
    assert safety2["reason"] == "low_score"
    assert len(fake_llm["calls"]) == calls_before, "拒答时不应调用大模型"


def test_red_flag_question_carries_notice(client: TestClient, new_user: dict, knowledge_base: dict, fake_llm, monkeypatch):
    """红旗症状提问：SSE 携带安全提示，且提示写入回答正文。"""
    fake_contexts = [
        {
            "chunk_id": 1,
            "document_id": 1,
            "document_name": "院内急救流程.md",
            "knowledge_base_id": knowledge_base["id"],
            "knowledge_base_name": knowledge_base["name"],
            "content": "急性胸痛患者应在 10 分钟内完成首份心电图。",
            "page": -1,
            "score": 0.95,
        }
    ]
    monkeypatch.setattr(chat_service, "retrieve_multi", lambda *args, **kwargs: fake_contexts)

    events = _stream(
        client,
        new_user["headers"],
        {"question": "患者突发胸痛伴呼吸困难，应该怎么处理？", "kb_ids": [knowledge_base["id"]]},
    )
    safety = next(event for event in events if event["type"] == "safety")
    assert safety["red_flags"], "应识别出急症关键词"
    assert "立即就近就医" in safety["notice"]

    session_id = events[0]["session_id"]
    messages = client.get(f"{API}/chat/sessions/{session_id}/messages", headers=new_user["headers"]).json()["data"]
    assert messages[1]["content"].startswith("【安全提示】")


def test_stream_keeps_history_rounds(client: TestClient, new_user: dict, fake_llm, allow_chat_without_kb):
    first = _stream(client, new_user["headers"], {"question": "第一个问题", "kb_ids": [], "history_rounds": 5})
    session_id = first[0]["session_id"]

    _stream(
        client,
        new_user["headers"],
        {"question": "第二个问题", "session_id": session_id, "kb_ids": [], "history_rounds": 5},
    )

    second_call_messages = fake_llm["calls"][-1]["messages"]
    roles = [item["role"] for item in second_call_messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert second_call_messages[-1]["content"].endswith("第二个问题")


def test_stream_history_rounds_zero(client: TestClient, new_user: dict, fake_llm, allow_chat_without_kb):
    first = _stream(client, new_user["headers"], {"question": "第一问", "kb_ids": []})
    session_id = first[0]["session_id"]
    _stream(
        client,
        new_user["headers"],
        {"question": "第二问", "session_id": session_id, "kb_ids": [], "history_rounds": 0},
    )
    messages = fake_llm["calls"][-1]["messages"]
    assert [item["role"] for item in messages] == ["system", "user"]


def test_session_auto_named_by_question(client: TestClient, new_user: dict, fake_llm, allow_chat_without_kb):
    events = _stream(client, new_user["headers"], {"question": "抗菌药物分级使用权限如何规定？", "kb_ids": []})
    session_id = events[0]["session_id"]
    sessions = client.get(f"{API}/chat/sessions", headers=new_user["headers"]).json()["data"]
    target = next(item for item in sessions if item["id"] == session_id)
    assert target["name"].startswith("抗菌药物分级使用权限")


@pytest.mark.integration
def test_real_llm_streaming(client: TestClient, new_user: dict, allow_chat_without_kb, require_llm):
    """真实调用通义千问，验证流式返回。"""
    _ = require_llm  # 模型全挂时自动 skip
    events = _stream(
        client,
        new_user["headers"],
        {"question": "请用一句话说明你能做什么。", "kb_ids": [], "max_tokens": 128},
    )
    answer = "".join(event.get("content", "") for event in events if event["type"] == "delta")
    assert len(answer) > 0
    assert any(event["type"] == "done" for event in events)
