"""Static monthly cash-flow projection."""

from __future__ import annotations

from riskguard.core.metrics import monthly_subscription_total
from riskguard.models import AssessmentRequest, CashflowPoint


def compute_cashflow(request: AssessmentRequest) -> list[CashflowPoint]:
    """Project fixed income against contractual payments and subscriptions.

    CashflowPoint.debt_payment represents all monthly fixed outflows under the
    frozen M0 contract: debt payments plus recurring subscription costs.
    """

    income_total = (
        request.income.monthly_disposable_allowance
        + request.income.monthly_part_time_income
    )
    subscription_total = monthly_subscription_total(request)
    running_surplus = 0.0
    series: list[CashflowPoint] = []
    for month_index in range(1, request.forecast_months + 1):
        debt_payment = subscription_total + sum(
            debt.monthly_payment
            for debt in request.debts
            if month_index <= debt.remaining_periods
        )
        surplus = income_total - debt_payment
        running_surplus += surplus
        series.append(
            CashflowPoint(
                month_index=month_index,
                income=round(income_total, 6),
                debt_payment=round(debt_payment, 6),
                surplus=round(surplus, 6),
                cumulative_surplus=round(running_surplus, 6),
            )
        )
    return series


def savings_buffer_warnings(
    cashflow: list[CashflowPoint], savings_balance: float
) -> list[str]:
    """Describe whether existing savings can absorb projected deficits."""

    negative_points = [point for point in cashflow if point.surplus < 0]
    if not negative_points:
        return []
    if savings_balance <= 0:
        return ["当前固定月支出高于月度可支配资金，且没有存款缓冲。"]

    for point in cashflow:
        if point.cumulative_surplus < -savings_balance:
            return [
                f"按当前固定收入测算，存款缓冲不足以覆盖第 {point.month_index} 个月的累计缺口。"
            ]
    return ["当前存款可覆盖本次预测期内的累计缺口，但固定支出已高于月度收入。"]
