from __future__ import annotations

import json
from pathlib import Path

import pytest

from riskguard.core import MODEL_VERSION, load_scorecard, run_assessment
from riskguard.data import load_demo_cases
from riskguard.models import (
    AssessmentAssumptions,
    AssessmentMetrics,
    AssessmentRequest,
    AssessmentResult,
    BehaviorProfile,
    CashflowPoint,
    Debt,
    Income,
    IrrResult,
    RecurringSubscription,
    RiskAssessment,
    RiskDimension,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def required_fields(model) -> set[str]:
    schema = model.model_json_schema()
    return set(schema.get("required", []))


def test_final_manifest_versions_match_runtime() -> None:
    manifest = load_json(CONTRACTS / "m2_final_contract.json")
    scorecard = load_scorecard()

    assert manifest["status"] == "final"
    assert manifest["model_version"] == MODEL_VERSION
    assert manifest["parameter_version"] == scorecard["version"]
    assert manifest["scorecard"]["draft_only"] is False
    assert scorecard["draft_only"] is False
    assert scorecard["version"] == "scorecard-2026.11-m2-final"
    assert (ROOT / manifest["input_port"]["schema_path"]).exists()
    assert (ROOT / manifest["output_port"]["schema_path"]).exists()
    assert (ROOT / manifest["scorecard"]["runtime_path"]).exists()


def test_request_required_fields_match_schema() -> None:
    schema = load_json(CONTRACTS / "assessment_request.schema.json")

    assert required_fields(AssessmentRequest) == set(schema["required"])
    assert required_fields(Income) == set(schema["$defs"]["income"]["required"])
    assert required_fields(Debt) == set(schema["$defs"]["debt"]["required"])
    assert required_fields(RecurringSubscription) == set(
        schema["$defs"]["recurring_subscription"]["required"]
    )
    assert required_fields(BehaviorProfile) == set(
        schema["$defs"]["behavior"].get("required", [])
    )


def test_result_required_fields_match_schema() -> None:
    schema = load_json(CONTRACTS / "assessment_result.schema.json")
    properties = schema["properties"]

    assert required_fields(AssessmentResult) == set(schema["required"])
    assert required_fields(AssessmentMetrics) == set(
        properties["metrics"]["required"]
    )
    assert required_fields(IrrResult) == set(
        properties["irr_results"]["items"]["required"]
    )
    assert required_fields(RiskAssessment) == set(properties["risk"]["required"])
    assert required_fields(RiskDimension) == set(
        properties["risk"]["properties"]["dimensions"]["items"]["required"]
    )
    assert required_fields(CashflowPoint) == set(
        properties["cashflow_series"]["items"]["required"]
    )
    assert required_fields(AssessmentAssumptions) == set(
        properties["assumptions"]["required"]
    )


def test_scorecard_and_result_dimension_ids_match() -> None:
    scorecard = load_scorecard()
    schema = load_json(CONTRACTS / "assessment_result.schema.json")
    risk_dimension_schema = schema["properties"]["risk"]["properties"]["dimensions"]
    schema_ids = set(risk_dimension_schema["items"]["properties"]["id"]["enum"])
    scorecard_ids = {dimension["id"] for dimension in scorecard["dimensions"]}
    contributor_ids = set(
        schema["properties"]["risk"]["properties"]["top_contributors"]["items"]["enum"]
    )

    assert scorecard_ids == schema_ids == contributor_ids


def test_all_demo_requests_and_results_follow_final_contract() -> None:
    request_schema = load_json(CONTRACTS / "assessment_request.schema.json")
    request_fields = set(request_schema["properties"])

    for case in load_demo_cases():
        assert set(case["request"]) <= request_fields
        request = AssessmentRequest.model_validate(case["request"])
        result = run_assessment(request)

        assert AssessmentResult.model_validate(result.model_dump()) == result
        assert result.model_version == "calc-2026.11-m2-final"
        assert result.parameter_version == "scorecard-2026.11-m2-final"
        assert result.risk.level == case["expected_level"]
        assert result.metrics.debt_to_income_ratio == pytest.approx(
            case["expected_metrics"]["debt_to_income_ratio"], abs=1e-3
        )
