"""Minimal deterministic safety checks for M4 explanations.

The complete violation suite belongs to M6. This module provides the minimum
guard required by M4-B so an LLM cannot silently surface a lender or approval
recommendation in the final explanation.
"""

from __future__ import annotations

import re

from riskguard.models.agent import Explanation, FIXED_BOUNDARY_NOTICE, RiskSource
from riskguard.models.assessment import AssessmentResult

FORBIDDEN_EXPLANATION_TERMS = (
    "借款平台",
    "贷款平台",
    "推荐平台",
    "哪家平台",
    "哪个平台",
    "保证收益",
    "承诺收益",
    "保证解决",
    "审批通过",
    "授信额度",
    "通过率",
    "放款",
    "以贷养贷",
)

FORBIDDEN_EXPLANATION_PATTERNS = (
    r"(贷款|分期|申请).{0,8}(可以批|能批|批得下来|能过|包过|稳过)",
    r"(提高|提升|增加).{0,6}(额度|授信)",
    r"(保证|承诺|稳赚|保本).{0,8}(收益|回报|赚钱)",
    r"(irr|真实年化).{0,12}(收益|回报|赚钱)",
    r"(建议|推荐).{0,8}(借钱|贷款|借贷|平台)",
    r"(用|靠).{0,8}(借新|新借款|贷款|借款).{0,8}(还旧|旧债|还款)",
)


def explanation_narrative(explanation: Explanation) -> str:
    return " ".join(
        [
            explanation.summary,
            *[item.title + item.detail for item in explanation.risk_sources],
            *explanation.actions,
            *explanation.education,
            *explanation.questions_to_consider,
        ]
    )


def is_safe_explanation(explanation: Explanation) -> bool:
    narrative = explanation_narrative(explanation)
    normalized = re.sub(r"\s+", "", narrative).lower()
    if any(term in normalized for term in FORBIDDEN_EXPLANATION_TERMS):
        return False
    if any(re.search(pattern, normalized) for pattern in FORBIDDEN_EXPLANATION_PATTERNS):
        return False
    if re.search(r"\d", narrative):
        return False
    return True


_DIMENSION_COPY: dict[str, tuple[str, str]] = {
    "debt_to_income": (
        "月供压力",
        "固定支出占可支配资金的比例需要关注。",
    ),
    "debt_stack": (
        "负债叠加",
        "多笔固定还款叠加后，月度现金流管理空间会变小。",
    ),
    "real_cost": (
        "真实成本",
        "分期成本应结合期限和还款安排一起理解，不能只看表面月供。",
    ),
    "behavior_resilience": (
        "行为与韧性",
        "收入波动和还款习惯会影响后续现金流安全边际。",
    ),
}

_SUMMARY_COPY = {
    "低风险": "当前风险信号相对平稳，仍需持续关注固定支出和现金流变化。",
    "关注": "当前存在需要关注的负债压力信号，建议持续核对现金流。",
    "中风险": "当前固定支出和负债结构对现金流形成明显压力。",
    "高风险": "当前负债压力较高，需要优先核对现金流和还款安排。",
}


def build_grounded_explanation(
    selection: Explanation,
    result: AssessmentResult,
) -> Explanation:
    """Rebuild explanation text from structured evidence only.

    The model may choose evidence dimensions, but free-form text is discarded.
    This keeps the final explanation deterministic and grounded in the tool
    result while preserving the existing Explanation API shape.
    """

    allowed_ids = {dimension.id for dimension in result.risk.dimensions}
    selected_ids = [
        item.dimension_id
        for item in selection.risk_sources
        if item.dimension_id in allowed_ids
    ]
    if not selected_ids:
        raise ValueError("explanation has no grounded dimensions")

    ordered_ids = list(dict.fromkeys(selected_ids))
    sources = [
        RiskSource(
            dimension_id=dimension_id,
            title=_DIMENSION_COPY[dimension_id][0],
            detail=_DIMENSION_COPY[dimension_id][1],
        )
        for dimension_id in ordered_ids
    ]
    return Explanation(
        summary=_SUMMARY_COPY[result.risk.level],
        risk_sources=sources,
        actions=[
            "先把每笔分期的月供和剩余期数写在一起，看看加起来会不会压到生活费。",
            "优先检查金额最高、期限最长的那一笔，不要只看单笔月供看起来不高。",
            "如果这个月已经要靠新增分期周转，先暂停新的消费分期，重新核对现金流。",
            "给自己留一点现金缓冲，遇到收入波动时先降低可选消费。",
        ],
        education=[
            "低月供不等于低总成本，应关注期限和真实成本。",
            "遇到还款压力时，应优先核对现金流并寻求可靠的学校或家庭支持。",
        ],
        questions_to_consider=[
            "收入下降时是否仍能覆盖固定支出？",
            "未来几个月是否有足够的现金缓冲？",
        ],
        boundary_notice=FIXED_BOUNDARY_NOTICE,
    )
