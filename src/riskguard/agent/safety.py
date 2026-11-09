"""Minimal deterministic safety checks for M4 explanations.

The complete violation suite belongs to M6. This module provides the minimum
guard required by M4-B so an LLM cannot silently surface a lender or approval
recommendation in the final explanation.
"""

from __future__ import annotations

import re

from riskguard.models.agent import Explanation

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
