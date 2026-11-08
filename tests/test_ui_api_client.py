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
