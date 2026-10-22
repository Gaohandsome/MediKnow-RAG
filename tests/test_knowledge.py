"""知识库增删改查与权限隔离测试。"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from tests.conftest import API


def _create(client: TestClient, headers: dict, **overrides) -> dict:
    payload = {
        "name": f"库-{uuid.uuid4().hex[:6]}",
        "description": "测试",
        "retrieval_mode": "hybrid",
        "chunk_size": 300,
        "chunk_overlap": 60,
        **overrides,
    }
    response = client.post(f"{API}/knowledge-bases", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_create_list_and_detail(client: TestClient, new_user: dict):
    kb = _create(client, new_user["headers"])
    assert kb["collection_name"] == settings.milvus_collection_prefix
    assert kb["document_count"] == 0

    listing = client.get(f"{API}/knowledge-bases", headers=new_user["headers"]).json()["data"]
    assert any(item["id"] == kb["id"] for item in listing)

    detail = client.get(f"{API}/knowledge-bases/{kb['id']}", headers=new_user["headers"])
    assert detail.status_code == 200
    assert detail.json()["data"]["name"] == kb["name"]


def test_duplicate_name_rejected(client: TestClient, new_user: dict):
    kb = _create(client, new_user["headers"])
    response = client.post(
        f"{API}/knowledge-bases",
        headers=new_user["headers"],
        json={"name": kb["name"], "description": "", "retrieval_mode": "hybrid", "chunk_size": 300, "chunk_overlap": 60},
    )
    assert response.status_code == 409


def test_invalid_chunk_params_rejected(client: TestClient, new_user: dict):
    response = client.post(
        f"{API}/knowledge-bases",
        headers=new_user["headers"],
        json={
            "name": f"库-{uuid.uuid4().hex[:6]}",
            "retrieval_mode": "hybrid",
            "chunk_size": 200,
            "chunk_overlap": 300,
        },
    )
    assert response.status_code == 422


def test_invalid_retrieval_mode_rejected(client: TestClient, new_user: dict):
    response = client.post(
        f"{API}/knowledge-bases",
        headers=new_user["headers"],
        json={"name": f"库-{uuid.uuid4().hex[:6]}", "retrieval_mode": "unknown", "chunk_size": 300},
    )
    assert response.status_code == 422


def test_update_and_delete(client: TestClient, new_user: dict):
    kb = _create(client, new_user["headers"])
    updated = client.patch(
        f"{API}/knowledge-bases/{kb['id']}",
        headers=new_user["headers"],
        json={"name": "改名后的库", "description": "新的描述"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "改名后的库"

    removed = client.delete(f"{API}/knowledge-bases/{kb['id']}", headers=new_user["headers"])
    assert removed.status_code == 200
    assert client.get(f"{API}/knowledge-bases/{kb['id']}", headers=new_user["headers"]).status_code == 404


def test_other_user_cannot_access(client: TestClient, new_user: dict, second_user: dict):
    kb = _create(client, new_user["headers"])
    response = client.get(f"{API}/knowledge-bases/{kb['id']}", headers=second_user["headers"])
    assert response.status_code == 404
    client.delete(f"{API}/knowledge-bases/{kb['id']}", headers=new_user["headers"])


def test_options_endpoint(client: TestClient, new_user: dict):
    _create(client, new_user["headers"])
    options = client.get(f"{API}/knowledge-bases/options", headers=new_user["headers"])
    assert options.status_code == 200
    assert isinstance(options.json()["data"], list)
