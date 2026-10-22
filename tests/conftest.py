"""pytest 共享夹具：测试库、鉴权、验证码、向量库清理。"""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

# 必须在导入应用配置之前覆盖环境变量（环境变量优先级高于 .env）
os.environ["MYSQL_DATABASE"] = "mediknow_test"
os.environ["MILVUS_COLLECTION_PREFIX"] = "test_kb_"
os.environ["UPLOAD_DIR"] = "data/test_uploads"
os.environ["LOG_DIR"] = "logs"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["RERANK_ENABLED"] = "false"
# 测试不调用真实大模型做查询理解，也不写问答缓存（避免跨用例污染）
os.environ["QUERY_REWRITE_ENABLED"] = "false"
os.environ["QA_CACHE_ENABLED"] = "false"
os.environ["REDIS_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.captcha import captcha_store  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.vector_store import get_vector_store  # noqa: E402

API = "/api/v1"


@pytest.fixture(scope="session", autouse=True)
def prepare_environment():
    """初始化测试库，结束后清理测试集合与上传目录。"""
    init_db()
    yield
    # 清理 Milvus 测试集合
    try:
        store = get_vector_store()
        for name in store.client.list_collections():
            if name.startswith("test_kb_"):
                store.client.drop_collection(collection_name=name)
    except Exception:  # noqa: BLE001
        pass

    Base.metadata.drop_all(bind=engine)
    upload_dir = Path("data/test_uploads")
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def client(prepare_environment):  # noqa: ARG001
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def fetch_captcha(client: TestClient) -> tuple[str, str]:
    """取验证码，并从内存存储里读取答案（仅测试使用）。"""
    response = client.get(f"{API}/auth/captcha")
    assert response.status_code == 200
    data = response.json()["data"]
    captcha_id = data["captcha_id"]
    code = captcha_store._data[captcha_id].code  # noqa: SLF001
    return captcha_id, code


@pytest.fixture()
def new_user(client: TestClient) -> dict:
    """注册并登录一个随机用户，返回账号与鉴权头。"""
    return register_and_login(client)


@pytest.fixture()
def second_user(client: TestClient) -> dict:
    """第二个用户，用于验证数据隔离。"""
    return register_and_login(client)


def register_and_login(client: TestClient) -> dict:
    """注册并登录一个随机用户。"""
    username = f"t{uuid.uuid4().hex[:10]}"
    password = "scrubbed-literal"
    captcha_id, code = fetch_captcha(client)
    register = client.post(
        f"{API}/auth/register",
        json={
            "username": username,
            "password": password,
            "confirm_password": password,
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert register.status_code == 200, register.text

    captcha_id, code = fetch_captcha(client)
    login = client.post(
        f"{API}/auth/login",
        json={
            "username": username,
            "password": password,
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert login.status_code == 200, login.text
    token = login.json()["data"]["access_token"]
    return {
        "username": username,
        "password": password,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture()
def knowledge_base(client: TestClient, new_user: dict):
    """创建一个混合检索知识库，测试结束后删除。"""
    response = client.post(
        f"{API}/knowledge-bases",
        headers=new_user["headers"],
        json={
            "name": f"测试库-{uuid.uuid4().hex[:6]}",
            "description": "pytest 自动创建",
            "retrieval_mode": "hybrid",
            "chunk_size": 200,
            "chunk_overlap": 40,
        },
    )
    assert response.status_code == 200, response.text
    kb = response.json()["data"]
    yield kb
    client.delete(f"{API}/knowledge-bases/{kb['id']}", headers=new_user["headers"])


@pytest.fixture(scope="session")
def require_llm():
    """真实调用大模型的用例：模型全部不可用（欠费/未授权）时跳过，而不是报红。"""
    from app.services.llm import probe_models

    snapshot = probe_models()
    if not snapshot.get("any_available"):
        reasons = "；".join(f"{i['model']}:{i['detail'][:40]}" for i in snapshot.get("candidates", [])[:2])
        pytest.skip(f"大模型暂不可用（{reasons}），跳过真实调用用例")
    return snapshot
