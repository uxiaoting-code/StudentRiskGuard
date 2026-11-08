"""TTL-limited in-memory scenario storage for M4-B."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable

from riskguard.models.memory import ScenarioDraft


class ScenarioStoreError(Exception):
    pass


class ScenarioNotFound(ScenarioStoreError):
    pass


class ScenarioExpired(ScenarioStoreError):
    pass


@dataclass(frozen=True)
class ScenarioRecord:
    scenario_id: str
    scenario: ScenarioDraft
    created_at: datetime
    expires_at: datetime


class ScenarioStore:
    def __init__(
        self,
        ttl_seconds: int = 1800,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        self.ttl_seconds = ttl_seconds
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._scenarios: dict[str, ScenarioRecord] = {}
        self._lock = RLock()

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _purge_expired_locked(self, now: datetime) -> int:
        expired = [
            scenario_id
            for scenario_id, record in self._scenarios.items()
            if record.expires_at <= now
        ]
        for scenario_id in expired:
            self._scenarios.pop(scenario_id, None)
        return len(expired)

    def create(self, scenario_id: str, scenario: ScenarioDraft) -> ScenarioRecord:
        now = self._now()
        with self._lock:
            self._purge_expired_locked(now)
            if scenario_id in self._scenarios:
                raise ValueError(f"scenario already exists: {scenario_id}")
            record = ScenarioRecord(
                scenario_id=scenario_id,
                scenario=scenario,
                created_at=now,
                expires_at=now + self._ttl,
            )
            self._scenarios[scenario_id] = record
            return record

    def get(self, scenario_id: str) -> ScenarioRecord:
        now = self._now()
        with self._lock:
            record = self._scenarios.get(scenario_id)
            if record is None:
                raise ScenarioNotFound(scenario_id)
            if record.expires_at <= now:
                self._scenarios.pop(scenario_id, None)
                raise ScenarioExpired(scenario_id)
            return record

    def delete(self, scenario_id: str) -> None:
        with self._lock:
            if scenario_id not in self._scenarios:
                raise ScenarioNotFound(scenario_id)
            self._scenarios.pop(scenario_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._scenarios)
