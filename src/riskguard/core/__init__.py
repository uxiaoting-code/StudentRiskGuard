"""Deterministic calculation core for StudentRiskGuard M2."""

from riskguard.core.cashflow import compute_cashflow, savings_buffer_warnings
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
