from __future__ import annotations

from typing import Any

from riskguard.ui import components


class FakeStreamlit:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.captions: list[str] = []
        self.writes: list[str] = []
        self.infos: list[str] = []

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def caption(self, message: str) -> None:
        self.captions.append(message)

    def write(self, message: str) -> None:
        self.writes.append(str(message))

    def markdown(self, message: str) -> None:
        self.writes.append(str(message))

    def info(self, message: str) -> None:
        self.infos.append(message)

    def subheader(self, message: str) -> None:
        self.writes.append(str(message))


def _render(response: dict[str, Any], monkeypatch) -> FakeStreamlit:
    fake = FakeStreamlit()
    monkeypatch.setattr(components, "st", fake)
    components.render_chat_response(response)
    return fake


def test_needs_more_info_ui_hides_internal_fields_and_shows_turn_budget(monkeypatch) -> None:
    fake = _render(
        {
            "status": "needs_more_info",
            "reply": "这笔分期现在大概还欠多少钱？",
            "missing_fields": [
                "debts[0].remaining_principal",
                "debts[0].remaining_periods",
            ],
            "clarification_turns": 2,
            "max_clarification_turns": 8,
            "remaining_clarification_turns": 6,
        },
        monkeypatch,
    )

    visible = "\n".join(fake.warnings + fake.captions)
    assert "debts[0]" not in visible
    assert "remaining_periods" not in visible
    assert "2/8" in visible
    assert "6" in visible


def test_clarification_limit_ui_offers_friendly_fallback(monkeypatch) -> None:
    fake = _render(
        {
            "status": "clarification_limit",
            "reply": (
                "我已经记录了你目前提供的信息。为了避免反复追问，"
                "你可以改用结构化表单继续补充，或者点击重新开始。"
            ),
            "missing_fields": ["debts[0].remaining_principal"],
            "clarification_turns": 8,
            "max_clarification_turns": 8,
            "remaining_clarification_turns": 0,
        },
        monkeypatch,
    )

    visible = "\n".join(fake.warnings + fake.captions)
    assert "结构化表单" in visible
    assert "8/8" in visible
    assert "debts[0]" not in visible


def test_unknown_apr_preview_is_not_rendered_as_zero(monkeypatch) -> None:
    fake = FakeStreamlit()
    monkeypatch.setattr(components, "st", fake)

    components.render_intake_preview(
        {
            "income": {
                "monthly_disposable_allowance": 2000,
                "monthly_part_time_income": 500,
            },
            "debts": [
                {
                    "label": "花呗",
                    "remaining_principal": 1000,
                    "monthly_payment": 100,
                    "remaining_periods": 10,
                }
            ],
        }
    )

    visible = "\n".join(fake.writes + fake.captions)
    assert "名义利率未知" in visible
    assert "真实成本解释受限" in visible
    assert "0.00%" not in visible
def test_completed_chat_response_forwards_debt_labels(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_assessment(result, *, title="风险报告", debt_labels=None):
        captured["debt_labels"] = debt_labels

    monkeypatch.setattr(components, "render_assessment", fake_assessment)
    monkeypatch.setattr(components, "render_explanation", lambda explanation: None)
    monkeypatch.setattr(components, "render_tool_activity", lambda activities: None)
    monkeypatch.setattr(components, "render_boundary_notice", lambda: None)

    components.render_chat_response(
        {
            "status": "completed",
            "assessment": {"dummy": True},
            "explanation": {},
            "tool_activity": [],
        },
        debt_labels={"debt_1": "花呗"},
    )

    assert captured["debt_labels"] == {"debt_1": "花呗"}
