"""M2 assessment orchestration."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from riskguard.core.cashflow import compute_cashflow, savings_buffer_warnings
from riskguard.core.irr import compute_irr_results
from riskguard.core.metrics import compute_metrics
from riskguard.core.scorecard import compute_risk, load_scorecard
from riskguard.models import (
    AssessmentAssumptions,
    AssessmentRequest,
    AssessmentResult,
)


MODEL_VERSION = "calc-2026.11-m2-final"


def _stable_id(prefix: str, request: AssessmentRequest, parameter_version: str) -> str:
    payload = (
        f"{MODEL_VERSION}|{parameter_version}|"
        f"{request.model_dump_json(exclude_none=True)}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def run_assessment(
    request: AssessmentRequest,
    *,
    scorecard: Mapping[str, Any] | None = None,
) -> AssessmentResult:
    """Run the complete deterministic M2 assessment pipeline."""

    config = dict(scorecard) if scorecard is not None else load_scorecard()
    parameter_version = str(config["version"])
    metrics = compute_metrics(request)
    irr_results = compute_irr_results(request)
    risk = compute_risk(request, metrics, irr_results, config)
    cashflow = compute_cashflow(request)

    warnings: list[str] = []
    unavailable_debts = [
        result.debt_id for result in irr_results if result.status == "unavailable"
    ]
    if unavailable_debts:
        warnings.append(
            "以下债务无法在支持区间内求解 IRR："
            + "、".join(unavailable_debts)
            + "。"
        )
    unknown_apr_debts = [
        debt.id for debt in request.debts if debt.nominal_apr is None
    ]
    if unknown_apr_debts:
        warnings.append(
            "以下债务的名义利率未知，真实成本解释受限："
            + "、".join(unknown_apr_debts)
            + "。IRR 仍仅依据本金、月供和期数计算，未包含未录入费用。"
        )
    if metrics.monthly_surplus < 0:
        warnings.append("当前月度固定支出已经高于月度可支配资金。")
    warnings.extend(savings_buffer_warnings(cashflow, request.savings_balance))
    if not request.debts:
        warnings.append("当前未录入正在还款的债务，评分只反映收入结构。")

    request_id = _stable_id("req", request, parameter_version)
    assessment_id = _stable_id("asm", request, parameter_version)
    return AssessmentResult(
        assessment_id=assessment_id,
        request_id=request_id,
        model_version=MODEL_VERSION,
        parameter_version=parameter_version,
        metrics=metrics,
        irr_results=irr_results,
        risk=risk,
        cashflow_series=cashflow,
        warnings=warnings,
        assumptions=AssessmentAssumptions(
            currency="CNY",
            income_constant=True,
            forecast_months=request.forecast_months,
        ),
    )
