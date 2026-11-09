"""Deterministic intent routing for the M4-B chat entry point."""

from __future__ import annotations

import re

from riskguard.agent.schemas import IntentName


_OUT_OF_SCOPE_TERMS = (
    "借款平台",
    "贷款平台",
    "推荐平台",
    "哪家平台",
    "哪个平台",
    "借钱",
    "贷款能不能",
    "能不能贷款",
    "审批",
    "授信额度",
    "提高额度",
    "通过率",
    "放款",
    "以贷养贷",
)
_SCENARIO_TERMS = ("如果", "假如", "要是", "假设")
_SCENARIO_ACTION_TERMS = ("新增", "再加", "再买", "多一笔", "分期")
_RISK_TERMS = ("为什么", "风险", "评分", "分数", "等级", "贡献", "哪一项", "影响最大")
_EDUCATION_TERMS = (
    "什么是",
    "irr",
    "真实年化",
    "名义利率",
    "现金流",
    "订阅",
    "会员",
    "预算",
    "理性消费",
    "存款",
    "兼职",
    "以贷养贷",
    "分期期限",
    "分期是什么",
    "分期",
)
_ASSESSMENT_TERMS = (
    "生活费",
    "兼职收入",
    "月供",
    "花呗",
    "分期",
    "本金",
    "期数",
    "利率",
    "订阅",
    "会员",
)


def classify_intent(
    message: str,
    *,
    has_draft: bool,
    has_session: bool,
) -> IntentName:
    """Route the message without asking an LLM to make the routing decision."""

    normalized = message.lower()

    # Safety routing takes priority even if an intake draft is active.
    if is_out_of_scope_message(normalized):
        return "out_of_scope"

    if has_draft:
        return "clarification"

    if _looks_like_scenario(normalized):
        return "scenario_simulation"

    if any(term in normalized for term in _RISK_TERMS):
        return "risk_explanation"

    if _looks_like_assessment_intake(normalized):
        return "assessment_intake"

    if any(term in normalized for term in _EDUCATION_TERMS):
        return "education"

    return "out_of_scope"


def is_out_of_scope_message(message: str) -> bool:
    normalized = message.lower()
    return any(term in normalized for term in _OUT_OF_SCOPE_TERMS)


def _looks_like_scenario(message: str) -> bool:
    has_hypothetical = any(term in message for term in _SCENARIO_TERMS)
    has_new_action = any(term in message for term in _SCENARIO_ACTION_TERMS)
    has_installment_context = (
        "分期" in message or "月供" in message or "买" in message
    )
    return has_hypothetical and has_new_action and has_installment_context


def _looks_like_assessment_intake(message: str) -> bool:
    has_number = bool(re.search(r"\d", message))
    has_finance_term = any(term in message for term in _ASSESSMENT_TERMS)
    has_description_signal = any(
        term in message for term in ("我有", "每个月", "每月还", "还剩", "生活费", "本金")
    )
    return has_finance_term and (has_number or has_description_signal)
