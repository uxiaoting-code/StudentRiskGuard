from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from riskguard.agent.intake import IntakeService
from riskguard.agent.runner import AgentRunner
from riskguard.agent.schemas import NaturalLanguageIntakeRequest
from riskguard.api.main import create_app
from riskguard.models import AssessmentRequest, Debt, FIXED_BOUNDARY_NOTICE, Income
from riskguard.services import AssessmentService, DraftStore, SessionStore
from riskguard.tools import ToolExecutor


class FakeChatModel:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected model call")
        response = self.responses.pop(0)
        return response(kwargs) if callable(response) else response


def extraction_response(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "status": payload.get("status", "complete"),
                            "draft": payload.get("draft"),
                            "missing_fields": payload.get("missing_fields", []),
                            "warnings": payload.get("warnings", []),
                            "question": payload.get("question"),
                        },
                        ensure_ascii=False,
                    ),
                }
            }
        ]
    }


def malformed_extraction_response() -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "```json\nnot-json\n```"}}
        ]
    }


def tool_call_response(kwargs: dict[str, Any]) -> dict[str, Any]:
    user_message = json.loads(kwargs["messages"][1]["content"])
    session_id = user_message["session_id"]
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_intake_1",
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
                            "summary": "当前固定支出对现金流形成压力。",
                            "risk_sources": [
                                {
                                    "dimension_id": "debt_to_income",
                                    "title": "月供压力",
                                    "detail": "固定支出占可支配资金的比例需要关注。",
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


def build_service(
    responses: list[Any],
) -> tuple[IntakeService, FakeChatModel, SessionStore, DraftStore]:
    store = SessionStore()
    drafts = DraftStore()
    model = FakeChatModel(responses)
    service = AssessmentService(store)
    runner = AgentRunner(
        session_store=store,
        tool_executor=ToolExecutor(service),
        llm_client=model,
    )
    intake = IntakeService(
        draft_store=drafts,
        session_store=store,
        agent_runner=runner,
        llm_client=model,
    )
    return intake, model, store, drafts


FULL_DRAFT = {
    "income": {
        "monthly_disposable_allowance": 2000,
        "monthly_part_time_income": 600,
    },
    "debts": [
        {
            "label": "花呗",
            "remaining_principal": 2400,
            "monthly_payment": 300,
            "remaining_periods": 8,
            "nominal_apr": 0.12,
        }
    ],
    "savings_balance": 0,
    "recurring_subscriptions": [{"label": "会员", "monthly_cost": 25}],
    "no_debts": False,
    "forecast_months": 12,
}


def test_full_intake_requires_confirmation_then_runs_existing_agent() -> None:
    service, model, sessions, drafts = build_service(
        [
            extraction_response({"draft": FULL_DRAFT}),
            tool_call_response,
            explanation_response(),
        ]
    )

    first = service.submit(
        NaturalLanguageIntakeRequest(message="我每个月生活费 2000，兼职 600，花呗每月 300。")
    )

    assert first.status == "ready_for_confirmation"
    assert first.missing_fields == []
    assert first.preview is not None
    assert len(drafts) == 1
    assert len(sessions) == 0

    response = service.confirm(first.conversation_id)

    assert response.status == "completed"
    assert response.degraded is False
    assert response.assessment is not None
    assert response.explanation is not None
    assert response.tool_activity[0].tool == "run_risk_assessment"
    assert response.tool_activity[0].status == "succeeded"
    assert len(sessions) == 1
    assert len(drafts) == 0
    assert len(model.calls) == 3


def test_missing_fields_are_asked_and_merged_across_turns() -> None:
    first_draft = {
        "income": {"monthly_disposable_allowance": 2000},
        "debts": [{"label": "花呗", "monthly_payment": 300}],
        "no_debts": False,
    }
    second_draft = {
        "income": {"monthly_part_time_income": 600},
        "debts": [
            {
                "label": "花呗",
                "remaining_principal": 2400,
                "remaining_periods": 8,
                "nominal_apr": 0.12,
            }
        ],
        "no_debts": False,
    }
    service, model, sessions, drafts = build_service(
        [
            extraction_response(
                {
                    "status": "needs_more_info",
                    "draft": first_draft,
                    "question": "请补充兼职收入、本金、期数和名义利率。",
                }
            ),
            extraction_response({"status": "complete", "draft": second_draft}),
        ]
    )

    first = service.submit(
        NaturalLanguageIntakeRequest(message="我每个月生活费 2000，花呗每月还 300。")
    )

    assert first.status == "needs_more_info"
    assert "income.monthly_part_time_income" in first.missing_fields
    assert "debts[0].remaining_principal" in first.missing_fields
    assert len(sessions) == 0
    assert len(drafts) == 1

    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="兼职 600，本金 2400，还有 8 期，利率 12%。",
        )
    )

    assert second.status == "ready_for_confirmation"
    assert second.missing_fields == []
    assert len(model.calls) == 2
    assert len(sessions) == 0


def test_invalid_numeric_extraction_does_not_reach_m2() -> None:
    invalid_draft = {
        "income": {"monthly_disposable_allowance": -10, "monthly_part_time_income": 0},
        "debts": [],
        "no_debts": True,
    }
    service, _, sessions, drafts = build_service(
        [extraction_response({"status": "invalid", "draft": invalid_draft})]
    )

    response = service.submit(NaturalLanguageIntakeRequest(message="我生活费负十元。"))

    assert response.status == "invalid"
    assert len(sessions) == 0
    assert response.warnings


def test_malformed_json_returns_invalid_without_crashing() -> None:
    service, _, sessions, drafts = build_service([malformed_extraction_response()])

    response = service.submit(NaturalLanguageIntakeRequest(message="这是一段无法解析的描述。"))

    assert response.status == "invalid"
    assert response.warnings
    assert len(sessions) == 0
    assert len(drafts) == 1


def test_raw_text_is_not_sent_to_report_prompt() -> None:
    raw_text = "这是我的私人描述，不能进入报告模型 xyz。"
    service, model, _, _ = build_service(
        [
            extraction_response({"draft": FULL_DRAFT}),
            tool_call_response,
            explanation_response(),
        ]
    )

    first = service.submit(NaturalLanguageIntakeRequest(message=raw_text))
    service.confirm(first.conversation_id)

    report_call = model.calls[-1]
    serialized_messages = json.dumps(report_call["messages"], ensure_ascii=False)
    assert "私人描述" not in serialized_messages
    assert "xyz" not in serialized_messages


def test_intake_and_confirm_api_use_same_service_chain() -> None:
    model = FakeChatModel(
        [
            extraction_response({"draft": FULL_DRAFT}),
            tool_call_response,
            explanation_response(),
        ]
    )
    api = TestClient(create_app(llm_client=model))

    intake_response = api.post(
        "/api/v1/agent/intake",
        json={"message": "我每个月生活费 2000，兼职 600，花呗每月 300。"},
    )
    assert intake_response.status_code == 200
    body = intake_response.json()
    assert body["status"] == "ready_for_confirmation"

    confirm_response = api.post(
        f"/api/v1/agent/intake/{body['conversation_id']}/confirm"
    )
    assert confirm_response.status_code == 200
    result = confirm_response.json()
    assert result["status"] == "completed"
    assert result["tool_activity"][0]["tool"] == "run_risk_assessment"


def test_zero_total_income_is_invalid() -> None:
    service, _, sessions, _ = build_service(
        [
            extraction_response(
                {
                    "status": "complete",
                    "draft": {
                        "income": {
                            "monthly_disposable_allowance": 0,
                            "monthly_part_time_income": 0,
                        },
                        "debts": [],
                        "no_debts": True,
                    },
                }
            )
        ]
    )

    response = service.submit(NaturalLanguageIntakeRequest(message="我没有生活费也没有兼职收入。"))

    assert response.status == "invalid"
    assert "income.positive_total" in response.missing_fields
    assert len(sessions) == 0


def test_explicit_no_debts_can_be_ready_for_confirmation() -> None:
    service, _, sessions, _ = build_service(
        [
            extraction_response(
                {
                    "status": "complete",
                    "draft": {
                        "income": {
                            "monthly_disposable_allowance": 2000,
                            "monthly_part_time_income": 600,
                        },
                        "debts": [],
                        "no_debts": True,
                    },
                }
            )
        ]
    )

    response = service.submit(NaturalLanguageIntakeRequest(message="我没有分期负债，生活费两千，兼职六百。"))

    assert response.status == "ready_for_confirmation"
    assert response.missing_fields == []
    assert len(sessions) == 0

def test_partial_subscription_is_asked_for_monthly_cost() -> None:
    service, _, sessions, _ = build_service(
        [
            extraction_response(
                {
                    "status": "needs_more_info",
                    "draft": {
                        "income": {
                            "monthly_disposable_allowance": 2000,
                            "monthly_part_time_income": 600,
                        },
                        "debts": [],
                        "no_debts": True,
                        "recurring_subscriptions": [{"label": "会员"}],
                    },
                }
            )
        ]
    )

    response = service.submit(NaturalLanguageIntakeRequest(message="我还有一个会员订阅。"))

    assert response.status == "needs_more_info"
    assert "recurring_subscriptions[0].monthly_cost" in response.missing_fields
    assert len(sessions) == 0
def test_confirm_accepts_valid_user_edited_request() -> None:
    service, _, sessions, drafts = build_service(
        [
            extraction_response(
                {
                    "status": "needs_more_info",
                    "draft": {
                        "income": {"monthly_disposable_allowance": 2000},
                        "debts": None,
                        "no_debts": None,
                    },
                }
            ),
            tool_call_response,
            explanation_response(),
        ]
    )
    first = service.submit(NaturalLanguageIntakeRequest(message="我每个月生活费 2000。"))
    edited = AssessmentRequest(
        session_id="user-supplied-id",
        income=Income(
            monthly_disposable_allowance=2000,
            monthly_part_time_income=600,
        ),
        debts=[
            Debt(
                id="user-supplied-debt-id",
                label="花呗",
                remaining_principal=2400,
                monthly_payment=300,
                remaining_periods=8,
                nominal_apr=0.12,
            )
        ],
    )

    response = service.confirm(first.conversation_id, edited)

    assert response.status == "completed"
    assert len(sessions) == 1
    assert len(drafts) == 0
def test_debt_can_be_added_after_no_debts_statement() -> None:
    service, _, sessions, drafts = build_service(
        [
            extraction_response(
                {
                    "status": "complete",
                    "draft": {
                        "income": {
                            "monthly_disposable_allowance": 2000,
                            "monthly_part_time_income": 600,
                        },
                        "debts": [],
                        "no_debts": True,
                    },
                }
            ),
            extraction_response(
                {
                    "status": "complete",
                    "draft": {
                        "debts": [
                            {
                                "label": "花呗",
                                "remaining_principal": 2400,
                                "monthly_payment": 300,
                                "remaining_periods": 8,
                                "nominal_apr": 0.12,
                            }
                        ]
                    },
                }
            ),
            tool_call_response,
            explanation_response(),
        ]
    )
    first = service.submit(NaturalLanguageIntakeRequest(message="我没有分期负债，生活费两千，兼职六百。"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="补充一下，我还有一笔花呗分期。",
        )
    )

    assert first.status == "ready_for_confirmation"
    assert second.status == "ready_for_confirmation"
    response = service.confirm(second.conversation_id)
    assert response.status == "completed"
    assert len(sessions) == 1
    assert len(drafts) == 0