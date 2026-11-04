"""In-memory anonymous session storage for M3.

No database or filesystem persistence is used. The default TTL is 30 minutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable

from riskguard.models import AssessmentRequest


class SessionStoreError(Exception):
    """Base error for session operations."""


class SessionNotFound(SessionStoreError):
    pass


class SessionExpired(SessionStoreError):
    pass


class SessionAlreadyExists(SessionStoreError):
    pass


@dataclass(frozen=True)
class SessionRecord:
    request: AssessmentRequest
    created_at: datetime
    expires_at: datetime


class SessionStore:
    """Thread-safe, TTL-limited in-memory session store."""

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
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = RLock()

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _purge_expired_locked(self, now: datetime) -> int:
        expired = [
            session_id
            for session_id, record in self._sessions.items()
            if record.expires_at <= now
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)
        return len(expired)

    def create(self, request: AssessmentRequest) -> SessionRecord:
        now = self._now()
        with self._lock:
            self._purge_expired_locked(now)
            if request.session_id in self._sessions:
                raise SessionAlreadyExists(request.session_id)
            record = SessionRecord(
                request=request,
                created_at=now,
                expires_at=now + self._ttl,
            )
            self._sessions[request.session_id] = record
            return record

    def get(self, session_id: str) -> SessionRecord:
        now = self._now()
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                raise SessionNotFound(session_id)
            if record.expires_at <= now:
                self._sessions.pop(session_id, None)
                raise SessionExpired(session_id)
            return record

    def delete(self, session_id: str) -> None:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                raise SessionNotFound(session_id)
            self._sessions.pop(session_id, None)

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked(self._now())

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
