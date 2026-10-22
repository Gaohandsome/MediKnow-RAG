"""注册 / 登录 / 验证码相关测试。"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.conftest import API, fetch_captcha


def test_captcha_returns_base64_image(client: TestClient):
    response = client.get(f"{API}/auth/captcha")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["captcha_id"]
    assert data["image"].startswith("data:image/png;base64,")


def test_register_and_login_success(client: TestClient):
    username = f"u{uuid.uuid4().hex[:8]}"
    password = f"T{uuid.uuid4().hex[:10]}"

    captcha_id, code = fetch_captcha(client)
    response = client.post(
        f"{API}/auth/register",
        json={
            "username": username,
            "password": password,
            "confirm_password": password,
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["username"] == username

    captcha_id, code = fetch_captcha(client)
    login = client.post(
        f"{API}/auth/login",
        json={"username": username, "password": password, "captcha_id": captcha_id, "captcha_code": code},
    )
    assert login.status_code == 200
    payload = login.json()["data"]
    assert payload["access_token"]
    assert payload["user"]["username"] == username


def test_register_rejects_password_mismatch(client: TestClient):
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        f"{API}/auth/register",
        json={
            "username": f"u{uuid.uuid4().hex[:8]}",
            "password": "scrubbed-literal",
            "confirm_password": "scrubbed-literal7",
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert response.status_code == 400
    assert "不一致" in response.json()["message"]


def test_register_rejects_duplicate_username(client: TestClient, new_user: dict):
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        f"{API}/auth/register",
        json={
            "username": new_user["username"],
            "password": "scrubbed-literal",
            "confirm_password": "scrubbed-literal",
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert response.status_code == 409


def test_login_rejects_wrong_captcha(client: TestClient, new_user: dict):
    captcha_id, _ = fetch_captcha(client)
    response = client.post(
        f"{API}/auth/login",
        json={
            "username": new_user["username"],
            "password": new_user["password"],
            "captcha_id": captcha_id,
            "captcha_code": "0000",
        },
    )
    assert response.status_code == 400
    assert "验证码" in response.json()["message"]


def test_login_rejects_wrong_password(client: TestClient, new_user: dict):
    captcha_id, code = fetch_captcha(client)
    response = client.post(
        f"{API}/auth/login",
        json={
            "username": new_user["username"],
            "password": "wrong-password",
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert response.status_code == 401


def test_captcha_cannot_be_reused(client: TestClient):
    captcha_id, code = fetch_captcha(client)
    username = f"u{uuid.uuid4().hex[:8]}"
    first = client.post(
        f"{API}/auth/register",
        json={
            "username": username,
            "password": "scrubbed-literal",
            "confirm_password": "scrubbed-literal",
            "captcha_id": captcha_id,
            "captcha_code": code,
        },
    )
    assert first.status_code == 200

    second = client.post(
        f"{API}/auth/login",
        json={"username": username, "password": "scrubbed-literal", "captcha_id": captcha_id, "captcha_code": code},
    )
    assert second.status_code == 400


def test_me_requires_token(client: TestClient):
    assert client.get(f"{API}/auth/me").status_code == 401


def test_me_returns_current_user(client: TestClient, new_user: dict):
    response = client.get(f"{API}/auth/me", headers=new_user["headers"])
    assert response.status_code == 200
    assert response.json()["data"]["username"] == new_user["username"]
