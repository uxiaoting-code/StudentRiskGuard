from __future__ import annotations

import json
from pathlib import Path

import pytest

from riskguard.core import run_assessment
from riskguard.data import load_demo_cases
from riskguard.models import AssessmentRequest, AssessmentResult, Income


ROOT = Path(__file__).resolve().parents[1]


def test_all_demo_cases_match_frozen_levels() -> None:
    for case in load_demo_cases():
        request = AssessmentRequest.model_validate(case["request"])
        result = run_assessment(request)

        assert isinstance(result, AssessmentResult)
        assert result.risk.level == case["expected_level"]
        if "debt_to_income_ratio" in case["expected_metrics"]:
            assert result.metrics.debt_to_income_ratio == pytest.approx(
                case["expected_metrics"]["debt_to_income_ratio"], abs=1e-3
            )
        if "debt_count" in case["expected_metrics"]:
            assert result.metrics.debt_count == case["expected_metrics"]["debt_count"]


def test_assessment_is_deterministic() -> None:
    case = next(
        item for item in load_demo_cases() if item["sample_id"] == "S-03"
    )
    request = AssessmentRequest.model_validate(case["request"])

    results = [run_assessment(request) for _ in range(20)]

    assert len({result.model_dump_json() for result in results}) == 1


def test_packaged_scorecard_matches_contract() -> None:
    contract = json.loads(
        (ROOT / "contracts" / "scorecard.example.json").read_text(encoding="utf-8")
    )
    packaged = json.loads(
        (
            ROOT / "src" / "riskguard" / "core" / "scorecard.json"
        ).read_text(encoding="utf-8")
    )

    assert packaged == contract


def test_no_debt_request_is_low_risk() -> None:
    request = AssessmentRequest(
        session_id="no-debt",
        income=Income(
            monthly_disposable_allowance=2000,
            monthly_part_time_income=500,
        ),
        debts=[],
        forecast_months=12,
    )

    result = run_assessment(request)

    assert result.metrics.debt_count == 0
    assert result.metrics.debt_to_income_ratio == 0
    assert result.risk.score == 0
    assert result.risk.level == "低风险"
    assert result.warnings == ["当前未录入正在还款的债务，评分只反映收入结构。"]
