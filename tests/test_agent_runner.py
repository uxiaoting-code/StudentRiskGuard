from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from riskguard.agent import AgentRunner, DeepSeekClient
from riskguard.agent.errors import LLMConfigurationError
from riskguard.api.main import create_app
from riskguard.models import AssessmentRequest, FIXED_BOUNDARY_NOTICE
from riskguard.services import AssessmentService, SessionStore
from riskguard.tools import ToolExecutor

ROOT = Path(__file__).resolve().parents[1]


def demo_request(sample_id: str = "S-03") -> AssessmentRequest:
    cases = json.loads((ROOT / "contracts" / "demo_cases.json").read_text(encoding="utf-8"))
    raw = next(case["request"] for case in cases if case["sample_id"] == sample_id)
    return AssessmentRequest.model_validate(raw)


def tool_call_response(session_id: str) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_test_1",
                            "type": "function",
                            "function": {
                                "name": "run_risk_assessment",
                                "arguments": json.dumps({"session_id": session_id}),
                            },
                        }
                    ],
                }
            }
        ]
    }


def explanation_response() -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "summary": "当前固定月供对现金流形成明显压力。",
                            "risk_sources": [
                                {
                                    "dimension_id": "debt_to_income",
                                    "title": "月供压力较高",
                                    "detail": "固定支出在可支配资金中的占比需要关注。",
                                }
                            ],
                            "actions": [
                                "核对每笔分期的月供和剩余期数。",
                                "检查未来数月的基本生活支出。",
                            ],
                            "education": [
                                "低月供不等于低总成本，应关注期限和真实成本。"
                            ],
                            "questions_to_consider": [
                                "收入下降时是否仍能覆盖固定支出？"
                            ],
                            "boundary_notice": FIXED_BOUNDARY_NOTICE,
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


class FakeChatModel:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected model call")
        return self.responses.pop(0)


def runner_for(session_id: str, responses: list[dict[str, Any]]) -> tuple[AgentRunner, FakeChatModel, AssessmentRequest]:
    store = SessionStore()
    request = demo_request("S-03").model_copy(update={"session_id": session_id})
    store.create(request)
    service = AssessmentService(store)
    executor = ToolExecutor(service)
    model = FakeChatModel(responses)
    return AgentRunner(
        session_store=store,
        tool_executor=executor,
        llm_client=model,
    ), model, request


def test_completed_agent_response_contains_real_tool_activity() -> None:
    runner, model, request = runner_for(
        "agent-ok",
        [tool_call_response("agent-ok"), explanation_response()],
    )

    response = runner.assess("agent-ok")

    assert response.status == "completed"
    assert response.degraded is False
    assert response.assessment is not None
    assert response.assessment.risk.level == "中风险"
    assert response.explanation is not None
    assert response.explanation.boundary_notice == FIXED_BOUNDARY_NOTICE
    assert response.tool_activity[0].tool == "run_risk_assessment"
    assert response.tool_activity[0].status == "succeeded"
    assert len(model.calls) == 2
    assert model.calls[0]["tools"]
    assert "tools" not in model.calls[1]


def test_model_does_not_receive_raw_financial_input() -> None:
    runner, model, _ = runner_for(
        "agent-private",
        [tool_call_response("agent-private"), explanation_response()],
    )

    runner.assess("agent-private")

    first_user_message = model.calls[0]["messages"][1]["content"]
    assert "agent-private" in first_user_message
    assert "monthly_disposable_allowance" not in first_user_message
    assert "remaining_principal" not in first_user_message
    assert "monthly_payment" not in first_user_message


def test_missing_tool_call_uses_degraded_fallback() -> None:
    empty = {"choices": [{"message": {"role": "assistant", "content": "no tool"}}]}
    runner, _, _ = runner_for("agent-no-tool", [empty, empty])

    response = runner.assess("agent-no-tool")

    assert response.status == "degraded"
    assert response.degraded is True
    assert response.assessment is not None
    assert response.explanation is not None
    assert response.explanation.boundary_notice == FIXED_BOUNDARY_NOTICE
    assert response.tool_activity[0].tool == "run_risk_assessment"


def test_invalid_explanation_uses_degraded_fallback() -> None:
    invalid = {"choices": [{"message": {"content": "not json"}}]}
    runner, _, _ = runner_for(
        "agent-invalid-json",
        [tool_call_response("agent-invalid-json"), invalid],
    )

    response = runner.assess("agent-invalid-json")

    assert response.status == "degraded"
    assert response.degraded is True
    assert response.assessment is not None
    assert response.explanation is not None


def test_agent_api_endpoint_returns_agent_response() -> None:
    store = SessionStore()
    request = demo_request("S-03").model_copy(update={"session_id": "agent-api"})
    store.create(request)
    model = FakeChatModel([tool_call_response("agent-api"), explanation_response()])
    api = TestClient(create_app(session_store=store, llm_client=model))

    response = api.post("/api/v1/agent/assess", json={"session_id": "agent-api"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["tool_activity"][0]["tool"] == "run_risk_assessment"
    assert body["assessment"]["risk"]["level"] == "中风险"


def test_deepseek_client_sends_tools_and_tool_choice() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_http_1",
                                    "type": "function",
                                    "function": {
                                        "name": "run_risk_assessment",
                                        "arguments": "{\"session_id\":\"http-session\"}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = DeepSeekClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        http_client=http_client,
    )
    try:
        response = client.complete(
            messages=[{"role": "user", "content": "test"}],
            tools=[{"type": "function", "function": {"name": "run_risk_assessment"}}],
            tool_choice={"type": "function", "function": {"name": "run_risk_assessment"}},
        )
    finally:
        http_client.close()

    assert response["choices"][0]["message"]["tool_calls"][0]["id"] == "call_http_1"
    assert captured["path"] == "/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["body"]["tools"][0]["function"]["name"] == "run_risk_assessment"
    assert captured["body"]["tool_choice"]["function"]["name"] == "run_risk_assessment"


def test_deepseek_client_requires_api_key() -> None:
    client = DeepSeekClient(api_key="", http_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))))
    try:
        with pytest.raises(LLMConfigurationError):
            client.complete(messages=[{"role": "user", "content": "test"}])
    finally:
        client._http_client.close()


def test_tool_call_cannot_switch_sessions() -> None:
    store = SessionStore()
    current = demo_request("S-03").model_copy(
        update={"session_id": "agent-current"}
    )
    other = demo_request("S-01").model_copy(
        update={"session_id": "agent-other"}
    )
    store.create(current)
    store.create(other)
    service = AssessmentService(store)
    model = FakeChatModel(
        [tool_call_response("agent-other"), explanation_response()]
    )
    runner = AgentRunner(
        session_store=store,
        tool_executor=ToolExecutor(service),
        llm_client=model,
    )

    response = runner.assess("agent-current")

    assert response.status == "degraded"
    assert response.assessment is not None
    assert response.assessment.request_id == service.assess(current).request_id
    assert len(model.calls) == 1
