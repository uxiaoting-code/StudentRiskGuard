from __future__ import annotations

import json
from typing import Any

import pytest

from riskguard.agent.intake import IntakeService
from riskguard.agent.runner import AgentRunner
from riskguard.agent.schemas import NaturalLanguageIntakeRequest
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
        return self.responses.pop(0)


def extraction_response(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "status": "needs_more_info",
                            "draft": draft,
                            "missing_fields": [],
                            "warnings": [],
                            "question": None,
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
    max_clarification_turns: int = 8,
) -> tuple[IntakeService, FakeChatModel, DraftStore]:
    sessions = SessionStore()
    drafts = DraftStore(max_clarification_turns=max_clarification_turns)
    model = FakeChatModel(responses)
    runner = AgentRunner(
        session_store=sessions,
        tool_executor=ToolExecutor(AssessmentService(sessions)),
        llm_client=model,
    )
    service = IntakeService(
        draft_store=drafts,
        session_store=sessions,
        agent_runner=runner,
        llm_client=model,
        max_clarification_turns=max_clarification_turns,
    )
    return service, model, drafts


def partial_principal_draft() -> dict[str, Any]:
    return {
        "income": {
            "monthly_disposable_allowance": 2000,
            "monthly_part_time_income": 500,
        },
        "debts": [
            {
                "label": "电动车分期",
                "monthly_payment": 500,
                "remaining_periods": 6,
                "nominal_apr_status": "unknown",
            }
        ],
        "no_debts": False,
    }


@pytest.mark.parametrize(
    "answer",
    ["3000", "3000元", "三千", "3千", "三千左右", "大概3000"],
)
def test_single_number_updates_pending_principal_without_model(answer: str) -> None:
    service, model, _ = build_service([extraction_response(partial_principal_draft())])

    first = service.submit(NaturalLanguageIntakeRequest(message="我有一笔电动车分期"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message=answer,
        )
    )

    assert second.status == "ready_for_confirmation"
    assert second.preview is not None
    assert second.preview["debts"][0]["remaining_principal"] == 3000
    assert len(model.calls) == 1
    assert "电动车分期" in first.reply


def test_monthly_payment_and_one_year_are_filled_deterministically() -> None:
    draft = {
        "income": {
            "monthly_disposable_allowance": 2000,
            "monthly_part_time_income": 500,
        },
        "debts": [
            {
                "label": "花呗",
                "remaining_principal": 3000,
                "nominal_apr_status": "unknown",
            }
        ],
        "no_debts": False,
    }
    service, model, _ = build_service([extraction_response(draft)])

    first = service.submit(NaturalLanguageIntakeRequest(message="我有花呗"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="每月300，还剩一年",
        )
    )

    assert second.status == "ready_for_confirmation"
    assert second.preview is not None
    debt = second.preview["debts"][0]
    assert debt["monthly_payment"] == 300
    assert debt["remaining_periods"] == 12
    assert len(model.calls) == 1


def test_unknown_rate_is_filled_without_second_model_call() -> None:
    draft = {
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
    }
    service, model, _ = build_service([extraction_response(draft)])

    first = service.submit(NaturalLanguageIntakeRequest(message="我有花呗和收入信息"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="利率不知道",
        )
    )

    assert second.status == "ready_for_confirmation"
    assert second.preview is not None
    assert second.preview["debts"][0].get("nominal_apr") is None
    assert len(model.calls) == 1


def test_ambiguous_numbers_do_not_overwrite_principal_and_question_changes() -> None:
    service, model, _ = build_service(
        [
            extraction_response(partial_principal_draft()),
            extraction_response(partial_principal_draft()),
        ]
    )

    first = service.submit(NaturalLanguageIntakeRequest(message="我有一笔电动车分期"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="3000和500",
        )
    )

    assert second.status == "needs_more_info"
    assert second.preview is not None
    assert "remaining_principal" not in second.preview["debts"][0]
    assert second.reply != first.reply
    assert "NO_PROGRESS_DETECTED" in second.warnings
    assert len(model.calls) == 2


def test_explicit_correction_overrides_previous_principal() -> None:
    draft = partial_principal_draft()
    draft["debts"][0]["nominal_apr_status"] = "not_mentioned"
    service, _, _ = build_service([extraction_response(draft)])

    first = service.submit(NaturalLanguageIntakeRequest(message="我有一笔电动车分期"))
    service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="3000",
        )
    )
    corrected = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="不对，本金是2500",
        )
    )

    assert corrected.preview is not None
    assert corrected.preview["debts"][0]["remaining_principal"] == 2500


def test_second_no_progress_turn_offers_structured_form() -> None:
    service, _, _ = build_service(
        [
            extraction_response(partial_principal_draft()),
            extraction_response(partial_principal_draft()),
            extraction_response(partial_principal_draft()),
        ]
    )
    first = service.submit(NaturalLanguageIntakeRequest(message="我有一笔电动车分期"))
    conversation_id = first.conversation_id

    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=conversation_id,
            message="继续补充",
        )
    )
    third = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=conversation_id,
            message="还是不知道",
        )
    )

    assert second.reply != first.reply
    assert "结构化表单" in third.reply


def test_settled_debt_does_not_shift_pending_debt_index() -> None:
    draft = {
        "income": {
            "monthly_disposable_allowance": 2000,
            "monthly_part_time_income": 500,
        },
        "debts": [
            {
                "label": "已还完白条",
                "monthly_payment": 100,
                "remaining_periods": 0,
            },
            {
                "label": "电动车分期",
                "monthly_payment": 500,
                "remaining_periods": 6,
                "nominal_apr_status": "unknown",
            },
        ],
        "no_debts": False,
    }
    service, _, drafts = build_service([extraction_response(draft)])

    first = service.submit(NaturalLanguageIntakeRequest(message="我有一笔已还完，一笔电动车分期"))
    state = drafts.get(first.conversation_id)
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="3000",
        )
    )

    assert state.pending_field == "debts[1].remaining_principal"
    assert state.current_debt_index == 1
    assert second.preview is not None
    assert second.preview["debts"][1]["remaining_principal"] == 3000


def test_original_amount_and_half_ratio_are_derived_by_python() -> None:
    draft = {
        "income": {
            "monthly_disposable_allowance": 2000,
            "monthly_part_time_income": 500,
        },
        "debts": [
            {
                "label": "电动车分期",
                "monthly_payment": 500,
                "remaining_periods": 6,
                "nominal_apr_status": "unknown",
            }
        ],
        "no_debts": False,
    }
    service, _, _ = build_service([extraction_response(draft)])

    response = service.submit(
        NaturalLanguageIntakeRequest(
            message="电动车分期买的六千，还剩一半没还"
        )
    )

    assert response.status == "ready_for_confirmation"
    assert response.preview is not None
    debt = response.preview["debts"][0]
    assert debt["original_amount"] == 6000
    assert debt["remaining_ratio"] == 0.5
    assert debt["remaining_principal"] == 3000
    assert "remaining_principal" in debt["derived_fields"]
    assert "REMAINING_PRINCIPAL_ESTIMATED" in response.warnings


def test_no_debt_answer_is_deterministic() -> None:
    draft = {
        "income": {
            "monthly_disposable_allowance": 2000,
            "monthly_part_time_income": 500,
        },
        "debts": None,
        "no_debts": None,
    }
    service, model, _ = build_service([extraction_response(draft)])

    first = service.submit(NaturalLanguageIntakeRequest(message="我每个月生活费2000，兼职500"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="没有负债，也没有分期",
        )
    )

    assert second.status == "ready_for_confirmation"
    assert second.preview is not None
    assert second.preview["debts"] == []
    assert len(model.calls) == 1

def test_ambiguous_monthly_statement_does_not_become_one_period() -> None:
    service, model, _ = build_service(
        [
            extraction_response(partial_principal_draft()),
            extraction_response(partial_principal_draft()),
        ]
    )
    first = service.submit(NaturalLanguageIntakeRequest(message="我有一笔电动车分期"))
    second = service.submit(
        NaturalLanguageIntakeRequest(
            conversation_id=first.conversation_id,
            message="一个月还300",
        )
    )

    assert second.status == "needs_more_info"
    assert second.preview is not None
    assert second.preview["debts"][0]["remaining_periods"] == 6
    assert second.preview["debts"][0]["monthly_payment"] == 500
    assert "remaining_principal" not in second.preview["debts"][0]
    assert len(model.calls) == 2
