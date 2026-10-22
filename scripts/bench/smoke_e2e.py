"""端到端冒烟脚本：注册 -> 建库 -> 上传四类文档 -> 流式问答。

前置：后端已在 http://127.0.0.1:8001 运行，且 DEBUG=true（验证码会写入日志，便于脚本读取）。

用法：python scripts/bench/smoke_e2e.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8001/api/v1"
ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "logs"


def read_captcha_code(captcha_id: str) -> str:
    """从日志里读取调试模式输出的验证码。"""
    prefix = captcha_id[:8]
    deadline = time.time() + 10
    while time.time() < deadline:
        for log_file in sorted(LOGS.glob("app_*.log"), reverse=True):
            text = log_file.read_text(encoding="utf-8", errors="ignore")
            matches = re.findall(rf"验证码 {prefix} 为 ([A-Z0-9]+)", text)
            if matches:
                return matches[-1]
        time.sleep(0.3)
    raise RuntimeError("未能从日志读取验证码，请确认 DEBUG=true 且日志目录正确")


def get_captcha(client: httpx.Client) -> tuple[str, str]:
    response = client.get(f"{BASE}/auth/captcha")
    data = response.json()["data"]
    return data["captcha_id"], read_captcha_code(data["captcha_id"])


def main() -> int:
    client = httpx.Client(timeout=300)
    username = f"demo{int(time.time()) % 100000}"
    # 演示账号口令每次随机生成，不写死在脚本里
    password = f"Smoke{uuid.uuid4().hex[:10]}"

    # 1. 注册 + 登录
    captcha_id, code = get_captcha(client)
    reg = client.post(
        f"{BASE}/auth/register",
        json={
            "username": username,
            "password": password,
            "confirm_password": password,
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    print("注册：", reg.status_code, reg.json().get("message"))

    captcha_id, code = get_captcha(client)
    login = client.post(
        f"{BASE}/auth/login",
        json={"username": username, "password": password, "captcha_id": captcha_id, "captcha_code": code},
    )
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("登录：", login.status_code)

    # 2. 建两个知识库
    def create_kb(name: str, desc: str) -> int:
        response = client.post(
            f"{BASE}/knowledge-bases",
            headers=headers,
            json={"name": name, "description": desc, "retrieval_mode": "hybrid", "chunk_size": 400, "chunk_overlap": 80},
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]["id"]

    kb_hr = create_kb(f"人事制度库{username[-4:]}", "员工手册与差旅报销制度")
    kb_pd = create_kb(f"产品资料库{username[-4:]}", "产品发布流程与客服 SLA")
    print("知识库：", kb_hr, kb_pd)

    # 3. 上传四类文档
    uploads = [
        (kb_hr, "员工手册.md"),
        (kb_hr, "差旅报销制度.pdf"),
        (kb_pd, "产品发布流程.pptx"),
        (kb_pd, "客户服务SLA.png"),
    ]
    doc_ids = []
    for kb_id, filename in uploads:
        path = ROOT / "data" / filename
        with path.open("rb") as handle:
            response = client.post(
                f"{BASE}/knowledge-bases/{kb_id}/documents",
                headers=headers,
                files={"file": (filename, handle, "application/octet-stream")},
                data={"chunk_size": "400", "chunk_overlap": "80", "retrieval_mode": "hybrid"},
            )
        assert response.status_code == 200, response.text
        doc_id = response.json()["data"]["id"]
        doc_ids.append((filename, doc_id))
        print(f"上传 {filename} -> doc {doc_id}")

    # 4. 等待解析完成
    deadline = time.time() + 600
    pending = dict(doc_ids)
    while pending and time.time() < deadline:
        for filename, doc_id in list(pending.items()):
            detail = client.get(f"{BASE}/documents/{doc_id}", headers=headers).json()["data"]
            if detail["status"] in {"completed", "failed"}:
                print(f"解析 {filename}：{detail['status']}，块数 {detail['chunk_count']}")
                pending.pop(filename)
        if pending:
            time.sleep(2)

    # 5. 流式问答
    payload = {
        "question": "员工每年有几天年假？一线城市出差住宿每晚上限多少？",
        "kb_ids": [kb_hr, kb_pd],
        "top_k": 5,
        "use_rerank": True,
        "history_rounds": 5,
    }
    answer = ""
    contexts = []
    with client.stream("POST", f"{BASE}/chat/stream", headers=headers, json=payload) as response:
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            if event["type"] == "contexts":
                contexts = event["contexts"]
            elif event["type"] == "delta":
                answer += event["content"]
            elif event["type"] == "error":
                print("流式错误：", event["message"])
            elif event["type"] == "done":
                print(f"完成，耗时 {event['latency_ms']} ms")

    print("\n===== 命中资料 =====")
    for index, item in enumerate(contexts, start=1):
        print(f"[{index}] {item['document_name']} 分数={item['score']} 内容={item['content'][:60]}...")
    print("\n===== 回答 =====")
    print(answer)

    client.close()
    ok = "5" in answer and ("600" in answer or "住宿" in answer)
    print("\n冒烟结果：", "PASS" if ok else "请人工确认答案")
    return 0


if __name__ == "__main__":
    sys.exit(main())
