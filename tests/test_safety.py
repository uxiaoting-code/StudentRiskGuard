from __future__ import annotations

from riskguard.agent.safety import build_grounded_explanation, is_safe_explanation
from riskguard.models import Explanation, FIXED_BOUNDARY_NOTICE, RiskSource


def explanation_with_summary(summary: str) -> Explanation:
    return Explanation(
        summary=summary,
        risk_sources=[
            RiskSource(
                dimension_id="debt_to_income",
                title="月供压力",
                detail="固定支出占可支配资金的比例需要关注。",
            )
        ],
        actions=["核对月供和剩余期数。", "检查未来数月必要支出。"],
        education=["低月供不等于低总成本。"],
        questions_to_consider=["收入下降时是否仍能覆盖？"],
        boundary_notice=FIXED_BOUNDARY_NOTICE,
    )


def test_approval_language_variants_are_blocked() -> None:
    assert not is_safe_explanation(explanation_with_summary("这笔贷款可以批。"))
    assert not is_safe_explanation(explanation_with_summary("这笔申请能过。"))
    assert not is_safe_explanation(explanation_with_summary("建议提高授信额度。"))


def test_irr_return_claim_is_blocked() -> None:
    assert not is_safe_explanation(
        explanation_with_summary("IRR代表未来收益。")
    )


def test_grounded_pressure_explanation_remains_allowed() -> None:
    assert is_safe_explanation(
        explanation_with_summary("当前固定支出对月度现金流形成压力。")
    )
def test_grounded_explanation_discards_freeform_model_text() -> None:
    from riskguard.models import AssessmentRequest

    request = AssessmentRequest.model_validate(
        {
            "session_id": "grounding-test",
            "income": {
                "monthly_disposable_allowance": 2200,
                "monthly_part_time_income": 800,
            },
            "debts": [
                {
                    "id": "d1",
                    "label": "购物分期",
                    "remaining_principal": 4800,
                    "monthly_payment": 520,
                    "remaining_periods": 10,
                    "nominal_apr": 0.12,
                }
            ],
            "forecast_months": 12,
        }
    )
    from riskguard.core import run_assessment

    result = run_assessment(request)
    raw = explanation_with_summary("模型自由生成的未经授权结论。")
    raw.actions[0] = "模型自由生成的行动建议。"

    grounded = build_grounded_explanation(raw, result)

    assert grounded.summary != raw.summary
    assert grounded.actions != raw.actions
    assert grounded.boundary_notice == FIXED_BOUNDARY_NOTICE
    assert all(
        source.dimension_id in {item.id for item in result.risk.dimensions}
        for source in grounded.risk_sources
    )
