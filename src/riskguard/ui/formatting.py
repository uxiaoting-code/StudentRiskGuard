"""Presentation-only formatting helpers for the M5 UI."""

from __future__ import annotations

from typing import Any


def format_currency(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"¥{number:,.2f}"


def format_ratio(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "—"


def format_rate(value: Any) -> str:
    return format_ratio(value)


def format_risk_level(value: Any) -> str:
    return str(value) if value not in (None, "") else "—"


def format_tool_status(value: Any) -> str:
    mapping = {
        "succeeded": "成功",
        "failed": "失败",
        "skipped": "跳过",
    }
    return mapping.get(str(value), str(value) if value is not None else "—")


def format_review_status(value: Any) -> str:
    mapping = {
        "pending": "待审核",
        "approved": "已审核",
    }
    return mapping.get(str(value), str(value) if value is not None else "—")
DIMENSION_LABELS = {
    "debt_to_income": "月供收入比",
    "debt_stack": "多笔负债叠加",
    "real_cost": "真实资金成本",
    "behavior_resilience": "行为与韧性",
}

RISK_DIMENSION_LABELS = DIMENSION_LABELS


def format_dimension(value: str | None) -> str:
    if not value:
        return "—"
    return DIMENSION_LABELS.get(value, value)


def format_debt_name(debt_id: str | None, labels: dict[str, str] | None = None) -> str:
    if not debt_id:
        return "—"
    if labels and debt_id in labels:
        return labels[debt_id]
    if debt_id.startswith("debt_"):
        suffix = debt_id.removeprefix("debt_")
        if suffix.isdigit():
            return f"第 {suffix} 笔分期"
    return debt_id
