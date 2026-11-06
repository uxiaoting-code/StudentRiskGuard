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
    if any(term in narrative for term in FORBIDDEN_EXPLANATION_TERMS):
        return False
    if re.search(r"\d", narrative):
        return False
    return True
