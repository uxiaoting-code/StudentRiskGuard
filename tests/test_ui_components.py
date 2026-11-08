from __future__ import annotations

from typing import Any

from riskguard.ui import components


class FakeStreamlit:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.captions: list[str] = []

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def caption(self, message: str) -> None:
        self.captions.append(message)


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