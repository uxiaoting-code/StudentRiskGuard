"""Safe deterministic explanation used when the interaction Agent fails."""

from __future__ import annotations

from riskguard.models import (
    FIXED_BOUNDARY_NOTICE,
    AssessmentResult,
    Explanation,
    RiskSource,
)

_TITLES = {
    "debt_to_income": "月供压力",
    "debt_stack": "负债叠加",
    "real_cost": "真实成本",
    "behavior_resilience": "行为与韧性",
}


def build_fallback_explanation(result: AssessmentResult) -> Explanation:
    top_dimension = max(
        result.risk.dimensions,
        key=lambda item: item.contribution,
    )
    title = _TITLES.get(top_dimension.id, "现金流压力")
    return Explanation(
        summary="确定性计算已完成，智能解读暂时不可用。",
        risk_sources=[
            RiskSource(
                dimension_id=top_dimension.id,
                title=title,
                detail="请结合页面中的指标和现金流数据查看当前压力来源。",
            )
        ],
        actions=[
            "核对每笔分期的月供和剩余期数。",
            "检查未来数月的基本生活支出是否受到影响。",
        ],
        education=[
            "低月供不等于低总成本，应同时关注期限和真实年化成本。"
        ],
        questions_to_consider=[
            "如果兼职收入下降，当前固定支出是否仍然可以覆盖？"
        ],
        boundary_notice=FIXED_BOUNDARY_NOTICE,
    )
