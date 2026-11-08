from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from riskguard.api.main import create_app
from riskguard.auth import AuthService, AuthStore


def auth_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            auth_service=AuthService(
                AuthStore(tmp_path / "auth.db"),
                token_ttl_minutes=60,
            )
        )
    )


def test_auth_api_register_login_me_logout(tmp_path: Path) -> None:
    client = auth_client(tmp_path)

    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "student_demo", "password": "securepass123"},
    )
    assert registered.status_code == 201
    token = registered.json()["token"]

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["username"] == "student_demo"

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "student_demo", "password": "securepass123"},
    )
    assert login.status_code == 200
    login_token = login.json()["token"]

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {login_token}"},
    )
    assert logout.status_code == 200

    after_logout = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_token}"},
    )
    assert after_logout.status_code == 401
    assert after_logout.json()["error"]["code"] == "INVALID_TOKEN"


def test_auth_api_duplicate_and_bad_password(tmp_path: Path) -> None:
    client = auth_client(tmp_path)
    payload = {"username": "student_demo", "password": "securepass123"}
    client.post("/api/v1/auth/register", json=payload)

    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "USERNAME_TAKEN"

    bad_login = client.post(
        "/api/v1/auth/login",
        json={"username": "student_demo", "password": "wrongpass123"},
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_auth_api_expired_token(tmp_path: Path) -> None:
    service = AuthService(
        AuthStore(tmp_path / "auth.db"),
        token_ttl_minutes=1,
    )
    client = TestClient(create_app(auth_service=service))
    token = client.post(
        "/api/v1/auth/register",
        json={"username": "expired_demo", "password": "securepass123"},
    ).json()["token"]

    # Move the session expiry into the past without waiting in real time.
    with service.store._connect() as connection:
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        connection.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE user_id = ?",
            (past, service.store.get_user_by_username("expired_demo")["id"]),
        )
        connection.commit()

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"
