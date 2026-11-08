from __future__ import annotations

from datetime import datetime, timedelta, timezone

from riskguard.services.chat_memory_store import ChatMemoryStore
from riskguard.services.retention import RetentionSweeper


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 9, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def test_retention_sweeper_purges_unaccessed_expired_memory() -> None:
    clock = FakeClock()
    memory = ChatMemoryStore(ttl_seconds=10, max_messages=8, clock=clock)
    memory.append("conv-expired", role="user", content="短期原文")
    sweeper = RetentionSweeper((memory,), interval_seconds=1)
    clock.now += timedelta(seconds=11)

    result = sweeper.purge_once()

    assert result["ChatMemoryStore"] == 1
    assert memory.get_optional("conv-expired") is None


def test_retention_sweeper_rejects_unbounded_interval() -> None:
    for interval in (0, 3601):
        try:
            RetentionSweeper((), interval_seconds=interval)
        except ValueError:
            pass
        else:
            raise AssertionError(f"interval should be rejected: {interval}")
