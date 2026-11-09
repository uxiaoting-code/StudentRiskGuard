from __future__ import annotations

from riskguard.ui.formatting import format_debt_name, format_dimension


def test_risk_dimensions_have_chinese_labels() -> None:
    assert format_dimension("debt_to_income") == "月供收入比"
    assert format_dimension("debt_stack") == "多笔负债叠加"
    assert format_dimension("real_cost") == "真实资金成本"
    assert format_dimension("behavior_resilience") == "行为与韧性"


def test_irr_debt_names_use_labels_or_friendly_fallback() -> None:
    assert format_debt_name("debt_1", {"debt_1": "花呗"}) == "花呗"
    assert format_debt_name("debt_2", {}) == "第 2 笔分期"
    assert format_debt_name(None, {}) == "—"