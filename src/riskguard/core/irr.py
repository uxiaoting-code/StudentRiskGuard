"""Monthly IRR calculation for fixed-payment debt."""

from __future__ import annotations

import math

from riskguard.models import AssessmentRequest, Debt, IrrResult


IRR_ASSUMPTION = "remaining_principal at t=0, fixed monthly payment thereafter"
LOW_RATE = -0.999999999
HIGH_RATE = 10.0
TOLERANCE = 1e-11
MAX_ITERATIONS = 240


def _npv(monthly_rate: float, debt: Debt) -> float:
    try:
        value = -debt.remaining_principal
        for month in range(1, debt.remaining_periods + 1):
            value += debt.monthly_payment / (1.0 + monthly_rate) ** month
        return value
    except OverflowError:
        return math.inf


def _solve_monthly_irr(debt: Debt) -> float | None:
    total_payment = debt.monthly_payment * debt.remaining_periods
    if math.isclose(total_payment, debt.remaining_principal, abs_tol=1e-10):
        return 0.0

    low = LOW_RATE
    high = HIGH_RATE
    low_value = _npv(low, debt)
    high_value = _npv(high, debt)
    if not math.isfinite(low_value) and low_value > 0:
        low_value = math.inf
    if low_value * high_value > 0:
        return None

    for _ in range(MAX_ITERATIONS):
        midpoint = (low + high) / 2.0
        midpoint_value = _npv(midpoint, debt)
        if abs(midpoint_value) <= TOLERANCE or high - low <= TOLERANCE:
            return midpoint
        if low_value * midpoint_value <= 0:
            high = midpoint
            high_value = midpoint_value
        else:
            low = midpoint
            low_value = midpoint_value
    return (low + high) / 2.0


def compute_debt_irr(debt: Debt) -> IrrResult:
    """Solve monthly and effective annualized IRR for one debt."""

    monthly_irr = _solve_monthly_irr(debt)
    if monthly_irr is None:
        return IrrResult(
            debt_id=debt.id,
            monthly_irr=None,
            annualized_irr=None,
            status="unavailable",
            assumption=IRR_ASSUMPTION,
        )
    return IrrResult(
        debt_id=debt.id,
        monthly_irr=monthly_irr,
        annualized_irr=(1.0 + monthly_irr) ** 12 - 1.0,
        status="ok",
        assumption=IRR_ASSUMPTION,
    )


def compute_irr_results(request: AssessmentRequest) -> list[IrrResult]:
    """Compute IRR independently for every debt in a request."""

    return [compute_debt_irr(debt) for debt in request.debts]
