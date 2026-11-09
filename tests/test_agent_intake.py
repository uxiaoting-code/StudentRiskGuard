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
    *,
    max_clarification_turns: int | None = None,
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
        max_clarification_turns=max_clarification_turns,
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
def test_settled_debts_and_subscription_do_not_block_assessment() -> None:
    service, _, sessions, drafts = build_service(
        [
            extraction_response(
                {
                    "status": "complete",
                    "draft": {
                        "income": {
                            "monthly_disposable_allowance": 2000,
                            "monthly_part_time_income": 500,
                        },
                        "debts": [
                            {"label": "先用后付1", "monthly_payment": 200, "remaining_periods": 0},
                            {"label": "先用后付2", "monthly_payment": 55, "remaining_periods": 0},
                            {"label": "先用后付3", "monthly_payment": 34, "remaining_periods": 0},
                            {
                                "label": "追剧平台会员",
                                "monthly_payment": 15,
                                "remaining_periods": None,
                            },
                        ],
                        "recurring_subscriptions": [],
                        "no_debts": False,
                    },
                }
            ),
            tool_call_response,
            explanation_response(),
        ]
    )

    first = service.submit(
        NaturalLanguageIntakeRequest(
            message=(
                "我每个月生活费2000，兼职收入500，购物平台有三笔先用后付，"
                "剩余期数为0，还款金额分别为200,55,34，免息。"
                "有一个追剧平台每月自动续费会员15元。"
            )
        )
    )

    assert first.status == "ready_for_confirmation"
    assert first.missing_fields == []
    assert first.preview is not None
    assert len(first.preview.get("debts", [])) == 3
    assert all(item["settled"] is True for item in first.preview["debts"])
    assert first.preview["recurring_subscriptions"] == [
        {"label": "追剧平台会员", "monthly_cost": 15.0}
    ]

    response = service.confirm(first.conversation_id)

    assert response.status == "completed"
    assert response.assessment is not None
    assert response.assessment.metrics.debt_count == 0
    assert len(sessions) == 1
    assert len(drafts) == 0

def test_first_input_does_not_count_as_a_clarification_turn() -> None:
    missing = extraction_response(
        {
            "status": "needs_more_info",
            "draft": {
                "income": {
                    "monthly_disposable_allowance": 2000,
                    "monthly_part_time_income": 500,
                },
                "debts": [{"label": "花呗", "monthly_payment": 300}],
                "no_debts": False,
            },
        }
    )
    service, model, _, _ = build_service(
        [missing, missing, missing],
        max_clarification_turns=2,
    )

    first = service.submit(NaturalLanguageIntakeRequest(message="第一次描述"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="第一次补充",
        )
    )
    third = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="第二次补充",
        )
    )
    fourth = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="第三次补充",
        )
    )

    assert first.status == "needs_more_info"
    assert first.clarification_turns == 0
    assert first.remaining_clarification_turns >= 1
    assert second.clarification_turns == 1
    assert third.clarification_turns == 2
    assert fourth.status == "clarification_limit"
    assert "MAX_CLARIFICATION_TURNS_REACHED" in fourth.warnings
    assert len(model.calls) == 3
def test_invalid_supplement_does_not_consume_a_clarification_turn() -> None:
    missing = extraction_response(
        {
            "status": "needs_more_info",
            "draft": {
                "income": {
                    "monthly_disposable_allowance": 2000,
                    "monthly_part_time_income": 500,
                },
                "debts": [{"label": "花呗", "monthly_payment": 300}],
                "no_debts": False,
            },
        }
    )
    invalid = extraction_response({"status": "invalid"})
    service, model, _, _ = build_service([missing, invalid, missing])

    first = service.submit(NaturalLanguageIntakeRequest(message="第一次描述"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="这段暂时无法解析",
        )
    )
    third = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="继续补充月供三百元",
        )
    )

    assert first.clarification_turns == 0
    assert second.status == "invalid"
    assert second.clarification_turns == 0
    assert third.status == "needs_more_info"
    assert third.clarification_turns == 1
    assert len(model.calls) == 3


def test_eight_supplements_are_allowed_then_limit_does_not_call_model() -> None:
    missing = extraction_response(
        {
            "status": "needs_more_info",
            "draft": {
                "income": {
                    "monthly_disposable_allowance": 2000,
                    "monthly_part_time_income": 500,
                },
                "debts": [{"label": "花呗", "monthly_payment": 300}],
                "no_debts": False,
            },
        }
    )
    service, model, _, _ = build_service(
        [missing] * 9,
        max_clarification_turns=8,
    )

    first = service.submit(NaturalLanguageIntakeRequest(message="第一次描述"))
    assert first.clarification_turns == 0
    conversation_id = first.conversation_id

    last = first
    for rounds in range(1, 9):
        last = service.submit(
            NaturalLanguageIntakeRequest(
                conversation_id=conversation_id,
                message=f"第{rounds}次补充",
            )
        )
        assert last.status == "needs_more_info"
        assert last.clarification_turns == rounds
        assert last.remaining_clarification_turns == 8 - rounds

    limited = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=conversation_id,
            message="第九次补充",
        )
    )

    assert limited.status == "clarification_limit"
    assert limited.clarification_turns == 8
    assert limited.remaining_clarification_turns == 0
    assert "结构化表单" in limited.reply
    assert "重新开始" in limited.reply
    assert "MAX_CLARIFICATION_TURNS_REACHED" in limited.warnings
    assert len(model.calls) == 9


def test_known_fields_are_not_asked_again_and_new_named_debt_is_appended() -> None:
    first_response = extraction_response(
        {
            "status": "needs_more_info",
            "draft": {
                "income": {
                    "monthly_disposable_allowance": 2000,
                    "monthly_part_time_income": 500,
                },
                "debts": [
                    {
                        "label": "花呗",
                        "remaining_principal": 1000,
                        "monthly_payment": 300,
                    }
                ],
                "no_debts": False,
            },
        }
    )
    second_response = extraction_response(
        {
            "status": "needs_more_info",
            "draft": {
                "debts": [
                    {
                        "label": "白条",
                        "remaining_principal": 800,
                        "monthly_payment": 200,
                        "remaining_periods": 4,
                        "nominal_apr": 0.12,
                    }
                ]
            },
        }
    )
    service, model, _, _ = build_service([first_response, second_response])

    first = service.submit(NaturalLanguageIntakeRequest(message="我有花呗和收入信息"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="那再补一个白条分期",
        )
    )

    assert "生活费" not in first.reply
    assert "兼职收入" not in first.reply
    assert second.preview is not None
    labels = [item["label"] for item in second.preview["debts"]]
    assert labels == ["花呗", "白条"]
    assert second.preview["debts"][0]["monthly_payment"] == 300
    second_prompt = json.loads(model.calls[1]["messages"][1]["content"])
    assert second_prompt["previous_question"] == first.reply
    assert second_prompt["existing_draft"]["income"]["monthly_disposable_allowance"] == 2000


def test_unknown_nominal_apr_can_complete_and_is_not_treated_as_zero() -> None:
    draft = json.loads(json.dumps(FULL_DRAFT, ensure_ascii=False))
    draft["debts"][0].pop("nominal_apr")
    service, _, sessions, _ = build_service(
        [
            extraction_response({"draft": draft}),
            tool_call_response,
            explanation_response(),
        ]
    )

    response = service.submit(
        NaturalLanguageIntakeRequest(message="利率不知道，其他信息都有。")
    )

    assert response.status == "ready_for_confirmation"
    assert "nominal_apr" not in response.preview["debts"][0]

    confirmed = service.confirm(response.conversation_id)
    assert confirmed.assessment is not None
    assert any("名义利率未知" in warning for warning in confirmed.assessment.warnings)
    assert len(sessions) == 1
def test_apr_not_mentioned_is_asked_once_then_unknown_is_accepted() -> None:
    missing_apr = extraction_response(
        {
            "status": "needs_more_info",
            "draft": {
                "income": {
                    "monthly_disposable_allowance": 2000,
                    "monthly_part_time_income": 500,
                },
                "debts": [
                    {
                        "label": "花呗",
                        "remaining_principal": 1000,
                        "monthly_payment": 300,
                        "remaining_periods": 5,
                        "nominal_apr_status": "not_mentioned",
                    }
                ],
                "no_debts": False,
            },
        }
    )
    unknown_apr = extraction_response(
        {
            "status": "complete",
            "draft": {
                "debts": [
                    {
                        "label": "花呗",
                        "nominal_apr": None,
                        "nominal_apr_status": "unknown",
                    }
                ]
            },
        }
    )
    service, model, _, _ = build_service([missing_apr, unknown_apr])

    first = service.submit(NaturalLanguageIntakeRequest(message="我有花呗和收入信息"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="利率我不知道。",
        )
    )

    assert first.status == "needs_more_info"
    assert any(field.endswith(".nominal_apr") for field in first.missing_fields)
    assert second.status == "ready_for_confirmation"
    assert second.preview is not None
    assert second.preview["debts"][0].get("nominal_apr") is None
    assert "nominal_apr_status" not in second.preview["debts"][0]
    second_prompt = json.loads(model.calls[1]["messages"][1]["content"])
    assert second_prompt["existing_draft"]["debts"][0]["nominal_apr_status"] == "not_mentioned"
