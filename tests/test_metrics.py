from __future__ import annotations

import pytest

from riskguard.core.metrics import (
    compute_metrics,
    monthly_debt_payment_total,
    monthly_fixed_outflow_total,
    monthly_subscription_total,
)
from riskguard.data.synthetic import load_demo_cases
from riskguard.models import AssessmentRequest


def request_for(sample_id: str) -> AssessmentRequest:
    case = next(
        item for item in load_demo_cases() if item["sample_id"] == sample_id
    )
    return AssessmentRequest.model_validate(case["request"])


def test_s03_metrics_match_frozen_example() -> None:
    request = request_for("S-03")
    metrics = compute_metrics(request)

    assert metrics.income_total == pytest.approx(3000)
    assert metrics.monthly_payment_total == pytest.approx(1200)
    assert metrics.debt_to_income_ratio == pytest.approx(0.4)
    assert metrics.remaining_debt_total == pytest.approx(9300)
    assert metrics.debt_count == 3
    assert metrics.monthly_surplus == pytest.approx(1800)
    assert metrics.surplus_ratio == pytest.approx(0.6)


def test_subscription_is_fixed_outflow_not_debt() -> None:
    request = request_for("S-05")
    metrics = compute_metrics(request)

    assert monthly_debt_payment_total(request) == pytest.approx(200)
    assert monthly_subscription_total(request) == pytest.approx(50)
    assert monthly_fixed_outflow_total(request) == pytest.approx(250)
    assert metrics.monthly_payment_total == pytest.approx(250)
    assert metrics.debt_to_income_ratio == pytest.approx(250 / 2600)
    assert metrics.debt_count == 1
