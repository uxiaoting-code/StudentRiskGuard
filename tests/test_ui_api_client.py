from __future__ import annotations

import json

import httpx
import pytest

from riskguard.ui.api_client import ApiClient, ApiClientError
from riskguard.ui.formatting import (
    format_currency,
    format_rate,
    format_review_status,
    format_risk_level,
)
from riskguard.ui.samples import load_demo_cases


def test_loads_five_demo_cases() -> None:
    cases = load_demo_cases()

    assert len(cases) == 5
    assert {case["sample_id"] for case in cases} == {
        "S-01",
        "S-02",
        "S-03",
        "S-04",
        "S-05",
    }


def test_formatting_helpers() -> None:
    assert format_currency(1234.5) == "¥1,234.50"
    assert format_rate(0.1234) == "12.34%"
    assert format_risk_level("中风险") == "中风险"
    assert format_review_status("approved") == "已审核"


def test_api_client_chat_sends_expected_payload() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "conversation_id": "conv-001",
                "status": "education_answer",
                "reply": "IRR是资金成本指标。",
                "missing_fields": [],
                "tool_activity": [],
                "review_status": "approved",
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ApiClient(base_url="http://test.local", http_client=http_client)
    try:
        result = client.chat("什么是IRR？", conversation_id="conv-001")
    finally:
        http_client.close()

    assert captured["path"] == "/api/v1/agent/chat"
    assert captured["body"] == {
        "message": "什么是IRR？",
        "conversation_id": "conv-001",
    }
    assert result["status"] == "education_answer"


def test_api_client_translates_http_error() -> None:
    http_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                422,
                json={"error": {"code": "BAD", "message": "输入不合法。"}},
            )
        )
    )
    client = ApiClient(base_url="http://test.local", http_client=http_client)
    try:
        with pytest.raises(ApiClientError) as error:
            client.submit_intake("描述")
    finally:
        http_client.close()

    assert error.value.status_code == 422
    assert error.value.message == "输入不合法。"

def test_api_client_auth_flow_sends_bearer_token() -> None:
    calls: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            (
                request.method,
                request.url.path,
                request.headers.get("authorization"),
            )
        )
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(
                200,
                json={
                    "user_id": "usr_1",
                    "username": "student_demo",
                    "token": "token-1",
                    "expires_at": "2026-11-08T12:00:00+00:00",
                },
            )
        if request.url.path == "/api/v1/auth/me":
            return httpx.Response(
                200,
                json={"user_id": "usr_1", "username": "student_demo"},
            )
        if request.url.path == "/api/v1/auth/logout":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ApiClient(base_url="http://test.local", http_client=http_client)
    try:
        login = client.login("student_demo", "securepass123")
        client.set_access_token(login["token"])
        me = client.me()
        client.logout()
    finally:
        http_client.close()

    assert me["username"] == "student_demo"
    assert calls[0] == ("POST", "/api/v1/auth/login", None)
    assert calls[1] == ("GET", "/api/v1/auth/me", "Bearer token-1")
    assert calls[2] == ("POST", "/api/v1/auth/logout", "Bearer token-1")


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        (
            [
                {
                    "type": "string_pattern_mismatch",
                    "loc": ["body", "username"],
                    "msg": "String should match pattern",
                }
            ],
            "用户名需为 3～32 位，只能使用英文字母、数字和下划线，例如 test_student_1109。",
        ),
        (
            [
                {
                    "type": "string_too_short",
                    "loc": ["body", "username"],
                    "msg": "String should have at least 3 characters",
                }
            ],
            "用户名至少需要 3 个字符。",
        ),
        (
            [
                {
                    "type": "string_too_short",
                    "loc": ["body", "password"],
                    "msg": "String should have at least 8 characters",
                }
            ],
            "密码至少需要 8 个字符。",
        ),
    ],
)
def test_api_client_maps_auth_validation_errors_to_friendly_messages(
    detail: list[dict],
    expected: str,
) -> None:
    http_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(422, json={"detail": detail})
        )
    )
    client = ApiClient(base_url="http://test.local", http_client=http_client)
    try:
        with pytest.raises(ApiClientError) as error:
            client.register("bad-name", "short")
    finally:
        http_client.close()

    assert error.value.message == expected
    for internal in ("username", "password", "body", "string_"):
        assert internal not in error.value.message


def test_api_client_unifies_invalid_login_credentials_message() -> None:
    http_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                401,
                json={
                    "error": {
                        "code": "INVALID_CREDENTIALS",
                        "message": "用户名或密码错误。",
                    }
                },
            )
        )
    )
    client = ApiClient(base_url="http://test.local", http_client=http_client)
    try:
        with pytest.raises(ApiClientError) as error:
            client.login("student_demo", "wrongpass123")
    finally:
        http_client.close()

    assert error.value.message == "用户名或密码错误，请检查后重试。"
