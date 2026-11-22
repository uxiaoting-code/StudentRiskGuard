"""Deterministic intent routing for the M4-B chat entry point."""

from __future__ import annotations

import re

from riskguard.agent.schemas import IntentName


_OUT_OF_SCOPE_PATTERNS = (
    re.compile(
        r"(推荐|介绍|告诉我|帮我找|帮忙找|选).{0,16}"
        r"(借款|贷款|借贷|借钱).{0,8}(平台|产品|渠道|服务)?"
    ),
    re.compile(
        r"(哪个|哪家|哪里|哪儿).{0,8}(平台|产品|渠道|服务).{0,10}"
        r"(借款|贷款|借贷|借钱|下款|放款)"
    ),
    re.compile(
        r"(哪个|哪家|哪里|哪儿).{0,8}(借款|贷款|借贷|借钱).{0,8}"
        r"(平台|产品|渠道|服务)"
    ),
    re.compile(
        r"(哪里|哪儿|什么地方).{0,8}(可以|能|能够).{0,6}"
        r"(借款|贷款|借钱)"
    ),
    re.compile(
        r"(借款|贷款|借贷).{0,10}(平台|产品|渠道|服务).{0,14}"
        r"(推荐|哪个|哪家|哪里|找)"
    ),
    re.compile(
        r"(能不能|可不可以|是否可以|是否|会不会).{0,12}"
        r"(借款|贷款|下款|放款|审批|批|通过)"
    ),
    re.compile(
        r"(我想|我要|想要).{0,8}(借款|贷款|借贷|借钱).{0,8}"
        r"(怎么办|怎么借|如何借|可以吗|行吗)"
    ),
    re.compile(r"(怎么|如何|怎样).{0,6}(借款|贷款|借贷|借钱)"),
    re.compile(r"(借款|贷款).{0,8}(能不能|可不可以|是否|会不会)"),
    re.compile(r"(提高|提升|增加).{0,8}(额度|授信)"),
    re.compile(r"(通过率|授信额度|放款结果|以贷养贷|借新还旧|包过)"),
)
_OUT_OF_SCOPE_TERMS = ("借款平台", "贷款平台", "借钱平台")
_SCENARIO_TERMS = ("如果", "假如", "要是", "假设")
_SCENARIO_ACTION_TERMS = ("新增", "再加", "再买", "多一笔", "分期")
_RISK_TERMS = ("为什么", "风险", "评分", "分数", "等级", "贡献", "哪一项", "影响最大")
_EDUCATION_QUESTION_TERMS = (
    "什么是",
    "是什么意思",
    "怎么算",
    "如何计算",
    "有什么区别",
    "为什么叫",
    "代表什么",
    "含义",
)
_EDUCATION_TOPIC_TERMS = (
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
    "分期",
    "月收入",
    "生活费",
)
_PERSONAL_FINANCE_TERMS = (
    "生活费",
    "收入",
    "月收入",
    "工资",
    "月工资",
    "到手",
    "零花钱",
    "爸妈给",
    "家里给",
    "父母给",
    "兼职",
    "打工",
    "接单",
    "奖学金",
    "补助",
    "月供",
    "花呗",
    "白条",
    "分期",
    "负债",
    "欠款",
    "本金",
    "期数",
    "利率",
    "订阅",
    "会员",
    "还完",
    "结清",
    "借钱",
    "贷款",
)
_PERSONAL_CONTEXT_TERMS = (
    "我",
    "本人",
    "俺",
    "家里",
    "爸妈",
    "父母",
    "自己",
)
_NO_DEBT_TERMS = ("没有负债", "没有分期", "没有欠款", "已经还完", "已经结清")


def classify_intent(
    message: str,
    *,
    has_draft: bool,
    has_session: bool,
) -> IntentName:
    """Route the message without asking an LLM to make the routing decision."""

    normalized = message.lower().strip()

    # Only explicit platform, approval, limit or lender-recommendation requests
    # are safety-refused. Describing one's own borrowing is valid intake.
    if is_out_of_scope_message(normalized):
        return "out_of_scope"

    explicit_education_question = _looks_like_explicit_education_question(normalized)
    personal_record = _looks_like_personal_record(normalized)

    if has_draft:
        if explicit_education_question and not personal_record:
            return "education"
        return "clarification"

    if _looks_like_scenario(normalized):
        return "scenario_simulation"

    if explicit_education_question and not personal_record:
        return "education"

    if any(term in normalized for term in _RISK_TERMS):
        return "risk_explanation"

    if _looks_like_assessment_intake(normalized):
        return "assessment_intake"

    if any(term in normalized for term in _EDUCATION_TOPIC_TERMS):
        return "education"

    return "general_help"


def is_out_of_scope_message(message: str) -> bool:
    normalized = message.lower().strip()
    if any(term in normalized for term in _OUT_OF_SCOPE_TERMS):
        return True
    return any(pattern.search(normalized) for pattern in _OUT_OF_SCOPE_PATTERNS)


def _looks_like_explicit_education_question(message: str) -> bool:
    has_question_form = any(term in message for term in _EDUCATION_QUESTION_TERMS)
    has_finance_topic = any(term in message for term in _EDUCATION_TOPIC_TERMS)
    return has_question_form and has_finance_topic


def _looks_like_personal_record(message: str) -> bool:
    if any(term in message for term in _NO_DEBT_TERMS):
        return True
    has_number = bool(re.search(r"\d", message))
    has_personal_context = any(term in message for term in _PERSONAL_CONTEXT_TERMS)
    has_finance_term = any(term in message for term in _PERSONAL_FINANCE_TERMS)
    if has_personal_context and has_finance_term:
        return True
    if has_number and has_finance_term:
        return True
    # "我一个月就三千" is a common oral income description even without
    # explicitly saying 收入 or 生活费.
    return bool(
        re.search(
            r"(我|本人|俺).{0,12}(一个月|每个月|每月).{0,12}"
            r"(\d|[零一二两三四五六七八九十百千万])",
            message,
        )
    )


def _looks_like_scenario(message: str) -> bool:
    has_hypothetical = any(term in message for term in _SCENARIO_TERMS)
    has_new_action = any(term in message for term in _SCENARIO_ACTION_TERMS)
    has_installment_context = (
        "分期" in message or "月供" in message or "买" in message
    )
    return has_hypothetical and has_new_action and has_installment_context


def _looks_like_assessment_intake(message: str) -> bool:
    return _looks_like_personal_record(message)
