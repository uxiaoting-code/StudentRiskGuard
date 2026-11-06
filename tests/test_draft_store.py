from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from riskguard.agent.schemas import AssessmentDraft, DraftState
from riskguard.services import DraftExpired, DraftStore, DraftTurnLimit


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 11, 6, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def state_for(conversation_id: str, clock: FakeClock, turn: int = 1) -> DraftState:
    return DraftState(
        conversation_id=conversation_id,
        draft=AssessmentDraft(),
        missing_fields=["income.monthly_disposable_allowance"],
        pending_question="请补充生活费。",
        clarification_turns=turn,
        created_at=clock.current,
        expires_at=clock.current + timedelta(seconds=60),
    )


def test_draft_expires_and_is_removed() -> None:
    clock = FakeClock()
    store = DraftStore(ttl_seconds=60, clock=clock)
    store.create(
        conversation_id="conv_expiry",
        draft=AssessmentDraft(),
        missing_fields=[],
        pending_question=None,
    )
    clock.advance(61)

    with pytest.raises(DraftExpired):
        store.get("conv_expiry")
    assert len(store) == 0


def test_draft_turn_limit_is_enforced() -> None:
    clock = FakeClock()
    store = DraftStore(ttl_seconds=60, max_clarification_turns=2, clock=clock)
    store.create(
        conversation_id="conv_limit",
        draft=AssessmentDraft(),
        missing_fields=[],
        pending_question=None,
        clarification_turns=2,
    )

    with pytest.raises(DraftTurnLimit):
        store.update(state_for("conv_limit", clock, turn=3))
