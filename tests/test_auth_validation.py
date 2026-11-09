from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from riskguard.auth.validation import (
    USERNAME_RULE_MESSAGE,
    validate_login_form,
    validate_registration_form,
)


def test_valid_registration_boundaries() -> None:
    assert validate_registration_form("abc", "password", "password") is None
    assert validate_registration_form("a" * 32, "p" * 8, "p" * 8) is None
    assert validate_registration_form("student_1109", "p" * 128, "p" * 128) is None


@pytest.mark.parametrize(
    ("username", "expected"),
    [
        ("", "请先输入用户名。"),
        ("ab", "用户名至少需要 3 个字符。"),
        ("a" * 33, "用户名最多只能有 32 个字符。"),
        ("张三同学", USERNAME_RULE_MESSAGE),
        ("test user", USERNAME_RULE_MESSAGE),
        ("test-user", USERNAME_RULE_MESSAGE),
        ("test@example.com", USERNAME_RULE_MESSAGE),
    ],
)
def test_invalid_usernames_get_friendly_messages(
    username: str,
    expected: str,
) -> None:
    assert validate_registration_form(username, "password", "password") == expected


@pytest.mark.parametrize(
    ("password", "expected"),
    [
        ("", "请先输入密码。"),
        ("1234567", "密码至少需要 8 个字符。"),
        ("p" * 129, "密码最多只能有 128 个字符。"),
    ],
)
def test_invalid_passwords_get_friendly_messages(
    password: str,
    expected: str,
) -> None:
    assert validate_registration_form("student_1109", password, password) == expected


def test_registration_requires_matching_confirmation() -> None:
    assert (
        validate_registration_form("student_1109", "password", "")
        == "请再次输入密码。"
    )
    assert (
        validate_registration_form("student_1109", "password", "different")
        == "两次输入的密码不一致，请重新确认。"
    )


def test_login_validation_does_not_require_confirmation() -> None:
    assert validate_login_form("student_1109", "password") is None
    assert validate_login_form("ab", "password") == "用户名至少需要 3 个字符。"
    assert validate_login_form("student_1109", "1234567") == "密码至少需要 8 个字符。"


def test_validation_messages_do_not_expose_internal_fields() -> None:
    messages = [
        validate_registration_form("bad-name", "password", "password"),
        validate_registration_form("student_1109", "short", "short"),
    ]
    for message in messages:
        assert message is not None
        for internal in ("username", "password", "body", "string_pattern_mismatch"):
            assert internal not in message

def test_auth_model_can_import_without_package_eager_loading() -> None:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import riskguard.models.auth; from riskguard.auth import AuthService",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
