"""Income, repayment and surplus metrics."""

from __future__ import annotations

from riskguard.models import AssessmentMetrics, AssessmentRequest


def monthly_debt_payment_total(request: AssessmentRequest) -> float:
    """Return the sum of contractual monthly debt payments."""

    return float(sum(debt.monthly_payment for debt in request.debts))


def monthly_subscription_total(request: AssessmentRequest) -> float:
    """Return the sum of active recurring subscription costs."""

    return float(
        sum(item.monthly_cost for item in request.recurring_subscriptions)
    )


def monthly_fixed_outflow_total(request: AssessmentRequest) -> float:
    """Return all recurring monthly outflows used for debt-pressure analysis.

    The frozen M0 contract defines monthly fixed outflow as debt payments plus
    recurring subscriptions. Subscriptions remain separate from debt principal
    and IRR calculations.
    """

    return monthly_debt_payment_total(request) + monthly_subscription_total(request)


def compute_metrics(request: AssessmentRequest) -> AssessmentMetrics:
    """Compute the deterministic M2 metrics for an assessment request."""

    income_total = (
        request.income.monthly_disposable_allowance
        + request.income.monthly_part_time_income
    )
    monthly_payment_total = monthly_fixed_outflow_total(request)
    monthly_surplus = income_total - monthly_payment_total
    return AssessmentMetrics(
        income_total=round(income_total, 6),
        monthly_payment_total=round(monthly_payment_total, 6),
        debt_to_income_ratio=round(monthly_payment_total / income_total, 8),
        remaining_debt_total=round(
            sum(debt.remaining_principal for debt in request.debts), 6
        ),
        debt_count=len(request.debts),
        monthly_surplus=round(monthly_surplus, 6),
        surplus_ratio=round(monthly_surplus / income_total, 8),
    )
