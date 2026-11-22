"""Deterministic calculation core for StudentRiskGuard M2."""

from riskguard.core.cashflow import compute_cashflow, savings_buffer_warnings
from riskguard.core.debt_calculation import (
    RATE_BASIS,
    calculate_debts,
    derive_debt_terms,
    monthly_rate_from_nominal_apr,
    payment_from_principal,
    principal_from_payment,
    scheduled_total_repayment,
)
from riskguard.core.engine import MODEL_VERSION, run_assessment
from riskguard.core.irr import compute_debt_irr, compute_irr_results
from riskguard.core.metrics import (
    monthly_debt_payment_total,
    monthly_fixed_outflow_total,
    monthly_subscription_total,
    compute_metrics,
)
from riskguard.core.scorecard import (
    DEFAULT_SCORECARD_PATH,
    compute_risk,
    interpolate_score,
    load_scorecard,
)

__all__ = [
    "DEFAULT_SCORECARD_PATH",
    "MODEL_VERSION",
    "RATE_BASIS",
    "calculate_debts",
    "derive_debt_terms",
    "monthly_rate_from_nominal_apr",
    "payment_from_principal",
    "principal_from_payment",
    "scheduled_total_repayment",
    "compute_cashflow",
    "compute_debt_irr",
    "compute_irr_results",
    "compute_metrics",
    "compute_risk",
    "interpolate_score",
    "load_scorecard",
    "monthly_debt_payment_total",
    "monthly_fixed_outflow_total",
    "monthly_subscription_total",
    "run_assessment",
    "savings_buffer_warnings",
]
