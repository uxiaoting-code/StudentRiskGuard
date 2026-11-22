from __future__ import annotations

import pytest

from riskguard.core.debt_calculation import (
    calculate_debt,
    derive_debt_terms,
    final_payment_from_total,
    payment_consistency,
    payment_from_principal,
    principal_from_payment,
    scheduled_total_repayment,
)
from riskguard.models import Debt


def test_equal_payment_formulas() -> None:
    payment = payment_from_principal(2400, 8, 0.12)
    principal = principal_from_payment(payment, 8, 0.12)

    assert payment == pytest.approx(313.657, abs=0.01)
    assert principal == pytest.approx(2400, abs=0.01)
    assert scheduled_total_repayment(payment, 8) == pytest.approx(2509.25, abs=0.02)


def test_zero_rate_branches() -> None:
    assert payment_from_principal(1200, 6, 0) == pytest.approx(200)
    assert principal_from_payment(200, 6, 0) == pytest.approx(1200)


def test_final_payment_and_total_derivation() -> None:
    assert final_payment_from_total(1000, 300, 4) == pytest.approx(100)
    derived = derive_debt_terms(
        principal=800,
        monthly_payment=300,
        periods=None,
        nominal_apr=None,
        total_repayment=1000,
    )
    assert derived.remaining_periods == 4
    assert derived.final_payment == 100
    assert derived.scheduled_total_repayment == 1000
    assert derived.estimated_financing_cost == 200


def test_inconsistent_payment_is_reported() -> None:
    status, warnings, expected = payment_consistency(
        principal=2400,
        monthly_payment=300,
        periods=8,
        nominal_apr=0.12,
    )
    assert status == "conflict"
    assert expected == pytest.approx(313.657, abs=0.01)
    assert "不一致" in warnings[0]


def test_debt_calculation_includes_total_and_cost() -> None:
    debt = Debt(
        id="d1",
        label="花呗",
        remaining_principal=4800,
        monthly_payment=520,
        remaining_periods=10,
        nominal_apr=None,
        derived_fields=["monthly_payment"],
    )
    calculation = calculate_debt(debt)
    assert calculation.scheduled_total_repayment == 5200
    assert calculation.estimated_financing_cost == 400
    assert calculation.field_sources["monthly_payment"] == "derived"
