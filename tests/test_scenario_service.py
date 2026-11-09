from __future__ import annotations

import json
from typing import Any

import pytest

from riskguard.models import AssessmentRequest, Debt
from riskguard.models.memory import ScenarioDraft
from riskguard.services import AssessmentService, ScenarioStore, SessionStore
from riskguard.services.scenario_service import ScenarioDebtLimit, ScenarioService


class FakeScenarioModel:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payloads.pop(0)


def scenario_response(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "status": payload.get("status", "complete"),
                            "scenario": payload.get("scenario"),
                            "missing_fields": payload.get("missing_fields", []),
                            "warnings": payload.get("warnings", []),
                            "question": payload.get("question"),
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


def request_with_debts(count: int) -> AssessmentRequest:
    debts = [
        Debt(
            id=f"d{index}",
            label=f"分期{index}",
            remaining_principal=1200 + index,
            monthly_payment=120,
            remaining_periods=12,
            nominal_apr=0.12,
        )
        for index in range(1, count + 1)
    ]
    return AssessmentRequest(
        session_id="s1",
        income={
            "monthly_disposable_allowance": 4000,
            "monthly_part_time_income": 0,
        },
        debts=debts,
    )


def build_scenario_service(
    payloads: list[dict[str, Any]],
) -> tuple[ScenarioService, ScenarioStore, SessionStore, FakeScenarioModel]:
    sessions = SessionStore()
    scenarios = ScenarioStore()
    model = FakeScenarioModel(payloads)
    service = ScenarioService(
        scenario_store=scenarios,
        session_store=sessions,
        assessment_service=AssessmentService(sessions),
        llm_client=model,
    )
    return service, scenarios, sessions, model


def test_partial_scenario_is_staged_and_merged_on_next_turn() -> None:
    service, scenarios, _, model = build_scenario_service(
        [
            scenario_response(
                {
                    "status": "needs_more_info",
                    "scenario": {"label": "新手机", "remaining_principal": 2400},
                    "missing_fields": ["monthly_payment", "remaining_periods"],
                    "question": "每月还多少，还要还几个月？",
                }
            ),
            scenario_response(
                {
                    "scenario": {
                        "monthly_payment": 300,
                        "remaining_periods": 8,
                    }
                }
            ),
        ]
    )

    first, scenario_id = service.extract_and_stage(
        "想加一笔手机分期，本金2400",
        conversation_id="c1",
        session_id="s1",
    )

    assert first.status == "needs_more_info"
    assert scenario_id is not None
    record = scenarios.get(scenario_id)
    assert record.scenario.label == "新手机"
    assert record.scenario.remaining_principal == 2400

    second, second_id = service.extract_and_stage(
        "每月还300，还要还8期，利率不知道",
        conversation_id="c1",
        session_id="s1",
        existing_scenario=record.scenario,
        existing_scenario_id=scenario_id,
        clarification_turns=0,
        previous_question=record.pending_question,
    )

    assert second.status == "complete"
    assert second_id == scenario_id
    merged = scenarios.get(scenario_id)
    assert merged.status == "ready"
    assert merged.scenario.remaining_principal == 2400
    assert merged.scenario.monthly_payment == 300
    assert merged.scenario.remaining_periods == 8
    assert merged.scenario.nominal_apr is None
    prompt = json.loads(model.calls[1]["messages"][1]["content"])
    assert prompt["existing_scenario"]["remaining_principal"] == 2400
    assert prompt["previous_question"] == "每月还多少，还要还几个月？"


def test_simulation_accepts_unknown_apr_and_removes_staged_scenario() -> None:
    service, scenarios, sessions, _ = build_scenario_service([])
    sessions.create(request_with_debts(1))
    record = scenarios.create(
        "sc-ok",
        ScenarioDraft(
            label="新手机",
            remaining_principal=2400,
            monthly_payment=300,
            remaining_periods=8,
            nominal_apr=None,
        ),
        conversation_id="c1",
        session_id="s1",
    )

    result = service.simulate(session_id="s1", scenario_id=record.scenario_id)

    assert result.monthly_payment_delta == 300
    assert any("名义利率未知" in warning for warning in result.scenario_assessment.warnings)
    assert len(scenarios) == 0


def test_simulation_rejects_twenty_first_debt_before_m2() -> None:
    service, scenarios, sessions, _ = build_scenario_service([])
    sessions.create(request_with_debts(20))
    record = scenarios.create(
        "sc-limit",
        ScenarioDraft(
            label="新手机",
            remaining_principal=2400,
            monthly_payment=300,
            remaining_periods=8,
            nominal_apr=0.12,
        ),
        conversation_id="c1",
        session_id="s1",
    )

    with pytest.raises(ScenarioDebtLimit):
        service.simulate(session_id="s1", scenario_id=record.scenario_id)
