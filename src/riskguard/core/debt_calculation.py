"""Deterministic debt repayment calculations.

Only fixed nominal APR, monthly compounding and equal-payment amortization are
modeled in this MVP. Fees are not inferred; a mismatch between user-provided
payment and the formula result is surfaced for confirmation instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from riskguard.models import Debt, DebtCalculation

RATE_BASIS = "fixed_nominal_apr_monthly_compounding_equal_payment"


def monthly_rate_from_nominal_apr(nominal_apr: float | None) -> float | None:
    if nominal_apr is None:
        return None
    if nominal_apr < 0 or nominal_apr > 1:
        raise ValueError("nominal_apr must be between 0 and 1")
    return nominal_apr / 12.0


def payment_from_principal(
    principal: float,
    periods: int,
    nominal_apr: float | None,
) -> float:
    if principal <= 0 or periods <= 0:
        raise ValueError("principal and periods must be positive")
    monthly_rate = monthly_rate_from_nominal_apr(nominal_apr)
    if monthly_rate is None:
        raise ValueError("nominal_apr is required")
    if monthly_rate == 0:
        return principal / periods
    factor = (1.0 + monthly_rate) ** periods
    return principal * monthly_rate * factor / (factor - 1.0)


def principal_from_payment(
    monthly_payment: float,
    periods: int,
    nominal_apr: float | None,
) -> float:
    if monthly_payment <= 0 or periods <= 0:
        raise ValueError("monthly_payment and periods must be positive")
    monthly_rate = monthly_rate_from_nominal_apr(nominal_apr)
    if monthly_rate is None:
        raise ValueError("nominal_apr is required")
    if monthly_rate == 0:
        return monthly_payment * periods
    factor = (1.0 + monthly_rate) ** periods
    return monthly_payment * (1.0 - 1.0 / factor) / monthly_rate


def scheduled_total_repayment(
    monthly_payment: float,
    periods: int,
    final_payment: float | None = None,
) -> float:
    if monthly_payment <= 0 or periods <= 0:
        raise ValueError("monthly_payment and periods must be positive")
    if final_payment is None:
        return monthly_payment * periods
    if periods == 1:
        return final_payment
    return monthly_payment * (periods - 1) + final_payment


def financing_cost(
    total_repayment: float,
    remaining_principal: float,
) -> float:
    return total_repayment - remaining_principal


def final_payment_from_total(
    total_repayment: float,
    monthly_payment: float,
    periods: int,
) -> float:
    if total_repayment <= 0 or monthly_payment <= 0 or periods <= 0:
        raise ValueError("total, monthly payment and periods must be positive")
    final_payment = total_repayment - monthly_payment * (periods - 1)
    if final_payment <= 0:
        raise ValueError("final payment must be positive")
    return final_payment


def payment_consistency(
    *,
    principal: float,
    monthly_payment: float,
    periods: int,
    nominal_apr: float | None,
) -> tuple[str, list[str], float | None]:
    if nominal_apr is None:
        return "unknown", ["名义利率未知，无法校验月供与利率的一致性。"], None
    expected = payment_from_principal(principal, periods, nominal_apr)
    tolerance = max(1.0, expected * 0.005)
    if abs(monthly_payment - expected) > tolerance:
        return (
            "conflict",
            [
                "你填写的月供与按名义利率推算的理论月供不一致。"
                f"理论月供约为 {expected:.2f} 元，请确认是否存在手续费或填写差异。"
            ],
            expected,
        )
    return "consistent", [], expected


def calculate_debt(debt: Debt) -> DebtCalculation:
    total = scheduled_total_repayment(
        debt.monthly_payment,
        debt.remaining_periods,
        debt.final_payment,
    )
    status, warnings, _ = payment_consistency(
        principal=debt.remaining_principal,
        monthly_payment=debt.monthly_payment,
        periods=debt.remaining_periods,
        nominal_apr=debt.nominal_apr,
    )
    derived = set(debt.derived_fields)
    fields = (
        "remaining_principal",
        "monthly_payment",
        "remaining_periods",
        "final_payment",
        "nominal_apr",
    )
    sources = {
        name: ("derived" if name in derived else "user" if getattr(debt, name) is not None else "unknown")
        for name in fields
    }
    return DebtCalculation(
        debt_id=debt.id,
        remaining_principal=round(debt.remaining_principal, 2),
        monthly_payment=round(debt.monthly_payment, 2),
        remaining_periods=debt.remaining_periods,
        final_payment=round(debt.final_payment, 2) if debt.final_payment is not None else None,
        nominal_apr=debt.nominal_apr,
        scheduled_total_repayment=round(total, 2),
        estimated_financing_cost=round(
            financing_cost(total, debt.remaining_principal),
            2,
        ),
        consistency_status=status,
        field_sources=sources,
        warnings=warnings,
    )


def calculate_debts(debts: list[Debt]) -> list[DebtCalculation]:
    return [calculate_debt(debt) for debt in debts]


@dataclass(slots=True)
class DebtDerivation:
    remaining_principal: float | None
    monthly_payment: float | None
    remaining_periods: int | None
    final_payment: float | None
    nominal_apr: float | None
    scheduled_total_repayment: float | None
    estimated_financing_cost: float | None
    derived_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    consistency_status: str = "unknown"


def derive_debt_terms(
    *,
    principal: float | None,
    monthly_payment: float | None,
    periods: int | None,
    nominal_apr: float | None,
    total_repayment: float | None = None,
    final_payment: float | None = None,
) -> DebtDerivation:
    derived: list[str] = []
    warnings: list[str] = []
    status = "unknown"

    if periods is None and total_repayment is not None and monthly_payment is not None:
        full = int(total_repayment // monthly_payment)
        remainder = round(total_repayment - full * monthly_payment, 6)
        if remainder == 0 and full >= 1:
            periods = full
            final_payment = None
        elif full >= 1 and remainder > 0:
            periods = full + 1
            final_payment = remainder
        if periods is not None and "remaining_periods" not in derived:
            derived.append("remaining_periods")
        if final_payment is not None and "final_payment" not in derived:
            derived.append("final_payment")

    if monthly_payment is None and principal is not None and periods is not None and nominal_apr is not None:
        monthly_payment = round(
            payment_from_principal(principal, periods, nominal_apr),
            2,
        )
        derived.append("monthly_payment")
        warnings.append("月供由本金、名义年利率和期数按等额本息公式估算。")

    if principal is None and monthly_payment is not None and periods is not None and nominal_apr is not None:
        principal = round(
            principal_from_payment(monthly_payment, periods, nominal_apr),
            2,
        )
        derived.append("remaining_principal")
        warnings.append("剩余本金由月供、名义年利率和期数按等额本息公式反推。")

    total: float | None = None
    if monthly_payment is not None and periods is not None:
        total = scheduled_total_repayment(monthly_payment, periods, final_payment)
    elif total_repayment is not None:
        total = total_repayment

    cost: float | None = None
    if total is not None and principal is not None:
        cost = financing_cost(total, principal)

    if principal is not None and monthly_payment is not None and periods is not None:
        status, conflict_warnings, _ = payment_consistency(
            principal=principal,
            monthly_payment=monthly_payment,
            periods=periods,
            nominal_apr=nominal_apr,
        )
        warnings.extend(conflict_warnings)

    return DebtDerivation(
        remaining_principal=principal,
        monthly_payment=monthly_payment,
        remaining_periods=periods,
        final_payment=final_payment,
        nominal_apr=nominal_apr,
        scheduled_total_repayment=round(total, 2) if total is not None else None,
        estimated_financing_cost=round(cost, 2) if cost is not None else None,
        derived_fields=derived,
        warnings=warnings,
        consistency_status=status,
    )
