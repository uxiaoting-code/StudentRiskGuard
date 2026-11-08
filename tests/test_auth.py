from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from riskguard.auth import AuthService, AuthServiceError, AuthStore


@pytest.fixture
def service(tmp_path: Path) -> AuthService:
    return AuthService(
        AuthStore(tmp_path / "auth.db"),
        token_ttl_minutes=60,
    )


def test_register_login_me_and_logout(service: AuthService) -> None:
    registered = service.register("student_demo", "securepass123")

    registered_user = service.authenticate_token(registered.token)
    assert registered_user.username == "student_demo"

    logged_in = service.login("student_demo", "securepass123")
    assert logged_in.user_id == registered.user_id
    assert logged_in.token != registered.token

    service.logout(logged_in.token)
    with pytest.raises(AuthServiceError) as error:
        service.authenticate_token(logged_in.token)
    assert error.value.code == "INVALID_TOKEN"


def test_duplicate_username_is_rejected(service: AuthService) -> None:
    service.register("student_demo", "securepass123")

    with pytest.raises(AuthServiceError) as error:
        service.register("STUDENT_DEMO", "anotherpass123")

    assert error.value.code == "USERNAME_TAKEN"
    assert error.value.status_code == 409


def test_wrong_password_is_rejected(service: AuthService) -> None:
    service.register("student_demo", "securepass123")

    with pytest.raises(AuthServiceError) as error:
        service.login("student_demo", "wrongpass123")

    assert error.value.code == "INVALID_CREDENTIALS"
    assert error.value.status_code == 401


def test_auth_database_contains_only_auth_fields(service: AuthService, tmp_path: Path) -> None:
    service.register("student_demo", "securepass123")
    db_path = tmp_path / "auth.db"
    assert db_path.exists()

    with sqlite3.connect(db_path) as connection:
        user_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)")
        }
        session_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(auth_sessions)")
        }

    assert user_columns == {
        "id",
        "username",
        "password_hash",
        "created_at",
        "consent_version",
    }
    assert session_columns == {
        "id",
        "user_id",
        "token_hash",
        "created_at",
        "expires_at",
    }
    stored = service.store.get_user_by_username("student_demo")
    assert stored is not None
    assert stored["password_hash"] != "securepass123"


def test_empty_or_invalid_token_is_rejected(service: AuthService) -> None:
    with pytest.raises(AuthServiceError) as error:
        service.authenticate_token("not-a-real-token")

    assert error.value.code == "INVALID_TOKEN"
