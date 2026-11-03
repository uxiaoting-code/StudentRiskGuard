from __future__ import annotations

import pytest

from riskguard.core.cashflow import compute_cashflow, savings_buffer_warnings
from riskguard.data.synthetic import load_demo_cases
from riskguard.models import AssessmentRequest, Debt, Income


def request_for(sample_id: str) -> AssessmentRequest:
    case = next(
        item for item in load_demo_cases() if item["sample_id"] == sample_id
    )
    return AssessmentRequest.model_validate(case["request"])


def test_s03_cashflow_uses_debt_lifecycle() -> None:
    cashflow = compute_cashflow(request_for("S-03"))

    assert len(cashflow) == 12
    assert cashflow[0].debt_payment == pytest.approx(1200)
    assert cashflow[7].debt_payment == pytest.approx(900)
    assert cashflow[8].debt_payment == pytest.approx(520)
    assert cashflow[10].debt_payment == pytest.approx(0)
    assert cashflow[-1].cumulative_surplus == pytest.approx(25660)


def test_s05_cashflow_includes_subscription_every_month() -> None:
    cashflow = compute_cashflow(request_for("S-05"))

    assert cashflow[0].debt_payment == pytest.approx(250)
    assert cashflow[-1].debt_payment == pytest.approx(250)
    assert cashflow[0].surplus == pytest.approx(2350)


def test_savings_warning_identifies_exhaustion_month() -> None:
    request = AssessmentRequest(
        session_id="deficit",
        income=Income(
            monthly_disposable_allowance=1000,
            monthly_part_time_income=0,
        ),
        debts=[
            Debt(
                id="d1",
                label="大额月供",
                remaining_principal=9000,
                monthly_payment=1500,
                remaining_periods=6,
                nominal_apr=0.18,
            )
        ],
        savings_balance=500,
        forecast_months=3,
    )

    warnings = savings_buffer_warnings(compute_cashflow(request), 500)

    assert warnings == ["按当前固定收入测算，存款缓冲不足以覆盖第 2 个月的累计缺口。"]
