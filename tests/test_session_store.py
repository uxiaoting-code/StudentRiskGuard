from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from riskguard.models import AssessmentRequest, Income
from riskguard.services import (
    SessionAlreadyExists,
    SessionExpired,
    SessionNotFound,
    SessionStore,
)


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 11, 4, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def request_for(session_id: str) -> AssessmentRequest:
    return AssessmentRequest(
        session_id=session_id,
        income=Income(
            monthly_disposable_allowance=2000,
            monthly_part_time_income=500,
        ),
        debts=[],
        forecast_months=12,
    )


def test_create_and_get_session() -> None:
    clock = FakeClock()
    store = SessionStore(ttl_seconds=1800, clock=clock)
    request = request_for("session-001")

    record = store.create(request)

    assert record.request is request
    assert store.get("session-001").request == request
    assert len(store) == 1


def test_duplicate_session_is_rejected() -> None:
    store = SessionStore(clock=FakeClock())
    request = request_for("duplicate")
    store.create(request)

    with pytest.raises(SessionAlreadyExists):
        store.create(request)


def test_expired_session_is_removed() -> None:
    clock = FakeClock()
    store = SessionStore(ttl_seconds=60, clock=clock)
    store.create(request_for("expired"))
    clock.advance(61)

    with pytest.raises(SessionExpired):
        store.get("expired")
    assert len(store) == 0


def test_delete_session() -> None:
    store = SessionStore(clock=FakeClock())
    store.create(request_for("delete-me"))
    store.delete("delete-me")

    with pytest.raises(SessionNotFound):
        store.get("delete-me")


def test_purge_expired_sessions() -> None:
    clock = FakeClock()
    store = SessionStore(ttl_seconds=30, clock=clock)
    store.create(request_for("purge-me"))
    clock.advance(31)

    assert store.purge_expired() == 1
    assert len(store) == 0
