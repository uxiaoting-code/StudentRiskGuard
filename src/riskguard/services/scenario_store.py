"""TTL-limited in-memory scenario storage for M4-B."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    conversation_id: str
    session_id: str
    scenario: ScenarioDraft
    missing_fields: tuple[str, ...]
    pending_question: str | None
    clarification_turns: int
    status: str
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

    def create(
        self,
        scenario_id: str,
        scenario: ScenarioDraft,
        *,
        conversation_id: str = "",
        session_id: str = "",
        missing_fields: list[str] | None = None,
        pending_question: str | None = None,
        clarification_turns: int = 0,
    ) -> ScenarioRecord:
        now = self._now()
        missing = tuple(missing_fields or [])
        with self._lock:
            self._purge_expired_locked(now)
            if scenario_id in self._scenarios:
                raise ValueError(f"scenario already exists: {scenario_id}")
            record = ScenarioRecord(
                scenario_id=scenario_id,
                conversation_id=conversation_id,
                session_id=session_id,
                scenario=scenario,
                missing_fields=missing,
                pending_question=pending_question,
                clarification_turns=clarification_turns,
                status="ready" if not missing else "draft",
                created_at=now,
                expires_at=now + self._ttl,
            )
            self._scenarios[scenario_id] = record
            return record

    def update(
        self,
        scenario_id: str,
        scenario: ScenarioDraft,
        *,
        missing_fields: list[str],
        pending_question: str | None,
        clarification_turns: int,
    ) -> ScenarioRecord:
        now = self._now()
        with self._lock:
            self._purge_expired_locked(now)
            current = self._scenarios.get(scenario_id)
            if current is None:
                raise ScenarioNotFound(scenario_id)
            missing = tuple(missing_fields)
            updated = replace(
                current,
                scenario=scenario,
                missing_fields=missing,
                pending_question=pending_question,
                clarification_turns=clarification_turns,
                status="ready" if not missing else "draft",
                expires_at=now + self._ttl,
            )
            self._scenarios[scenario_id] = updated
            return updated

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

    def delete_by_conversation(self, conversation_id: str) -> int:
        with self._lock:
            scenario_ids = [
                scenario_id
                for scenario_id, record in self._scenarios.items()
                if record.conversation_id == conversation_id
            ]
            for scenario_id in scenario_ids:
                self._scenarios.pop(scenario_id, None)
            return len(scenario_ids)

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked(self._now())

    def __len__(self) -> int:
        with self._lock:
            return len(self._scenarios)
