from __future__ import annotations

import pytest

from riskguard.agent.intents import classify_intent


def test_personal_description_routes_to_assessment_intake() -> None:
    intent = classify_intent(
        "我每个月生活费2200，兼职800，购物分期本金4800，每月520，还剩10期，名义利率12%。",
        has_draft=False,
        has_session=False,
    )

    assert intent == "assessment_intake"


def test_hypothetical_installment_routes_to_scenario_simulation() -> None:
    intent = classify_intent(
        "如果我新增一笔分期，本金2400，每月300，8期，利率12%，会怎样？",
        has_draft=False,
        has_session=True,
    )

    assert intent == "scenario_simulation"


def test_education_question_routes_to_education() -> None:
    intent = classify_intent(
        "什么是IRR？",
        has_draft=False,
        has_session=False,
    )

    assert intent == "education"


def test_lender_recommendation_routes_out_of_scope() -> None:
    intent = classify_intent(
        "推荐一个借款平台，哪个贷款通过率高？",
        has_draft=False,
        has_session=False,
    )

    assert intent == "out_of_scope"

def test_general_installment_question_routes_to_education() -> None:
    intent = classify_intent(
        "分期是什么？",
        has_draft=False,
        has_session=False,
    )

    assert intent == "education"

@pytest.mark.parametrize(
    "message",
    [
        "我现在月收入2000，还有800的零花钱。",
        "我现在的月收入是3000",
        "我一个月爸妈给2000，兼职800",
        "我一个月就三千，够不够用",
        "我没有负债，也没有分期",
        "我借钱买了个手机，现在每月还500",
        "我之前找朋友借钱买了手机",
        "我哪个贷款先还",
    ],
)
def test_oral_personal_finance_descriptions_route_to_intake(message: str) -> None:
    assert (
        classify_intent(message, has_draft=False, has_session=False)
        == "assessment_intake"
    )


@pytest.mark.parametrize(
    "message",
    [
        "月收入是什么意思",
        "生活费是什么意思",
        "兼职收入怎么算",
    ],
)
def test_explicit_finance_concept_questions_route_to_education(message: str) -> None:
    assert classify_intent(message, has_draft=False, has_session=False) == "education"


@pytest.mark.parametrize(
    "message",
    [
        "推荐一个借款平台",
        "我能不能贷款，哪个平台通过率高",
        "哪里可以借钱，最好包过",
        "帮我找个贷款产品",
        "我想贷款买手机，应该怎么办",
        "如何借钱最划算",
    ],
)
def test_explicit_lender_requests_remain_out_of_scope(message: str) -> None:
    assert classify_intent(message, has_draft=False, has_session=False) == "out_of_scope"


def test_unknown_input_routes_to_general_help_not_lending_refusal() -> None:
    assert (
        classify_intent("今天天气不错", has_draft=False, has_session=False)
        == "general_help"
    )


def test_active_draft_allows_explicit_education_question() -> None:
    assert (
        classify_intent("什么是IRR？", has_draft=True, has_session=False)
        == "education"
    )


def test_active_draft_treats_short_number_as_clarification() -> None:
    assert classify_intent("3000", has_draft=True, has_session=False) == "clarification"
