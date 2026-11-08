from __future__ import annotations

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