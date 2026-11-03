from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from riskguard import __version__
from riskguard.api.main import app
from riskguard.models import (
    FIXED_BOUNDARY_NOTICE,
    AgentResponse,
    AssessmentMetrics,
    AssessmentRequest,
    AssessmentResult,
    AssessmentAssumptions,
    CashflowPoint,
    Debt,
    Explanation,
    Income,
    IrrResult,
    RecurringSubscription,
    RiskAssessment,
    RiskDimension,
    RiskSource,
    ToolActivity,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
client = TestClient(app)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def demo_request(sample_id: str = "S-03") -> dict:
    cases = load_json(CONTRACTS / "demo_cases.json")
    return next(case["request"] for case in cases if case["sample_id"] == sample_id)


def assessment_example() -> dict:
    text = (ROOT / "docs" / "04_接口与数据契约.md").read_text(encoding="utf-8")
    start = text.index('```json\n{\n  "assessment_id": "asm_01JABCDEF"')
    body_start = start + len("```json\n")
    body_end = text.index("```", body_start)
    return json.loads(text[body_start:body_end])


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "studentriskguard-api",
        "version": __version__,
    }


def test_valid_demo_request_parses() -> None:
    request = AssessmentRequest.model_validate(demo_request())

    assert request.session_id == "demo-s03"
    assert len(request.debts) == 3
    assert request.forecast_months == 12
    assert request.savings_balance == 0
    assert request.recurring_subscriptions == []


def test_s05_subscription_contract_shape() -> None:
    request = AssessmentRequest.model_validate(demo_request("S-05"))

    assert request.savings_balance == 6000
    assert len(request.recurring_subscriptions) == 3
    assert request.recurring_subscriptions[0].label == "B站连续包月会员"
    assert request.recurring_subscriptions[0].monthly_cost == 25


def test_zero_total_income_is_rejected() -> None:
    payload = demo_request()
    payload["income"] = {
        "monthly_disposable_allowance": 0,
        "monthly_part_time_income": 0,
    }

    with pytest.raises(ValidationError) as error:
        AssessmentRequest.model_validate(payload)

    assert "income total must be greater than zero" in str(error.value)


def test_duplicate_debt_ids_are_rejected() -> None:
    payload = demo_request()
    payload["debts"][1]["id"] = payload["debts"][0]["id"]

    with pytest.raises(ValidationError) as error:
        AssessmentRequest.model_validate(payload)

    assert "debt ids must be unique" in str(error.value)


def test_unknown_fields_are_rejected() -> None:
    payload = demo_request()
    payload["student_id"] = "not-allowed"

    with pytest.raises(ValidationError) as error:
        AssessmentRequest.model_validate(payload)

    assert "Extra inputs are not permitted" in str(error.value)


def test_assessment_result_example_parses() -> None:
    result = AssessmentResult.model_validate(assessment_example())

    assert result.metrics.income_total == 3000
    assert result.metrics.debt_to_income_ratio == 0.4
    assert result.risk.score == 59
    assert result.risk.level == "中风险"
    assert len(result.cashflow_series) == 12


def test_completed_agent_response_parses() -> None:
    result = AssessmentResult.model_validate(assessment_example())
    response = AgentResponse(
        request_id=result.request_id,
        status="completed",
        degraded=False,
        tool_activity=[
            ToolActivity(
                tool="run_risk_assessment",
                status="succeeded",
                latency_ms=18,
            )
        ],
        assessment=result,
        explanation=Explanation(
            summary="当前负债叠加已经对月度现金流形成明显压力。",
            risk_sources=[
                RiskSource(
                    dimension_id="debt_to_income",
                    title="月供占用较高",
                    detail="固定月供占可支配收入的比重偏高。",
                )
            ],
            actions=["核对每笔分期的成本。", "检查未来三个月的必要支出。"],
            education=["低月供不等于低总成本。"],
            questions_to_consider=["兼职收入下降时还能覆盖月供吗？"],
            boundary_notice=FIXED_BOUNDARY_NOTICE,
        ),
        error=None,
    )

    assert response.status == "completed"
    assert response.tool_activity[0].tool == "run_risk_assessment"


def test_contract_field_sets_match_schemas() -> None:
    request_schema = load_json(CONTRACTS / "assessment_request.schema.json")
    result_schema = load_json(CONTRACTS / "assessment_result.schema.json")
    agent_schema = load_json(CONTRACTS / "agent_response.schema.json")

    assert set(AssessmentRequest.model_fields) == set(request_schema["properties"])
    assert set(Income.model_fields) == set(request_schema["$defs"]["income"]["properties"])
    assert set(Debt.model_fields) == set(request_schema["$defs"]["debt"]["properties"])
    assert set(RecurringSubscription.model_fields) == set(
        request_schema["$defs"]["recurring_subscription"]["properties"]
    )
    assert set(AssessmentResult.model_fields) == set(result_schema["properties"])
    assert set(AssessmentMetrics.model_fields) == set(
        result_schema["properties"]["metrics"]["properties"]
    )
    assert set(IrrResult.model_fields) == set(
        result_schema["properties"]["irr_results"]["items"]["properties"]
    )
    assert set(RiskAssessment.model_fields) == set(
        result_schema["properties"]["risk"]["properties"]
    )
    assert set(RiskDimension.model_fields) == set(
        result_schema["properties"]["risk"]["properties"]["dimensions"]["items"]["properties"]
    )
    assert set(CashflowPoint.model_fields) == set(
        result_schema["properties"]["cashflow_series"]["items"]["properties"]
    )
    assert set(AssessmentAssumptions.model_fields) == set(
        result_schema["properties"]["assumptions"]["properties"]
    )
    assert set(AgentResponse.model_fields) == set(agent_schema["properties"])
    assert set(Explanation.model_fields) == set(
        agent_schema["properties"]["explanation"]["oneOf"][0]["properties"]
    )
    assert set(ToolActivity.model_fields) == set(
        agent_schema["properties"]["tool_activity"]["items"]["properties"]
    )
