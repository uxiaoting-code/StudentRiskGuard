from __future__ import annotations

import copy

import pytest

from riskguard.core.irr import compute_irr_results
from riskguard.core.metrics import compute_metrics
from riskguard.core.scorecard import (
    compute_risk,
    interpolate_score,
    load_scorecard,
    validate_scorecard,
)
from riskguard.data.synthetic import load_demo_cases
from riskguard.models import AssessmentRequest


def request_for(sample_id: str) -> AssessmentRequest:
    case = next(
        item for item in load_demo_cases() if item["sample_id"] == sample_id
    )
    return AssessmentRequest.model_validate(case["request"])


def test_dti_scorecard_breakpoints() -> None:
    config = load_scorecard()
    dti_dimension = next(
        item for item in config["dimensions"] if item["id"] == "debt_to_income"
    )
    points = dti_dimension["points"]

    assert interpolate_score(0.299, points, "step") == pytest.approx(0)
    assert interpolate_score(0.3, points, "step") == pytest.approx(12)
    assert interpolate_score(0.399, points, "step") == pytest.approx(12)
    assert interpolate_score(0.4, points, "step") == pytest.approx(24)
    assert interpolate_score(0.5, points, "step") == pytest.approx(35)


def test_s03_matches_frozen_level_and_score() -> None:
    request = request_for("S-03")
    metrics = compute_metrics(request)
    irr_results = compute_irr_results(request)
    risk = compute_risk(request, metrics, irr_results)

    assert risk.score == 50
    assert risk.level == "中风险"
    assert [item.id for item in risk.dimensions] == [
        "debt_to_income",
        "debt_stack",
        "real_cost",
        "behavior_resilience",
    ]
    assert risk.top_contributors == [
        "debt_to_income",
        "real_cost",
        "debt_stack",
    ]


def test_invalid_weight_sum_is_rejected() -> None:
    config = copy.deepcopy(load_scorecard())
    config["dimensions"][0]["weight"] = 0.5

    with pytest.raises(ValueError, match="weights must sum to 1"):
        validate_scorecard(config)
