"""In-memory draft storage for M4-A natural-language intake.

Draft records contain structured, extracted fields only. The original user
message is never stored here. Records expire automatically and are deleted
after a confirmed assessment.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable

from riskguard.models.memory import AssessmentDraft, DraftState


class DraftStoreError(Exception):
    """Base error for draft operations."""


class DraftNotFound(DraftStoreError):
    pass


class DraftExpired(DraftStoreError):
    pass


class DraftTurnLimit(DraftStoreError):
    pass


class DraftStore:
    """Thread-safe, TTL-limited in-memory draft store."""

    def __init__(
        self,
        ttl_seconds: int = 1800,
        max_clarification_turns: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        maximum = (
            max_clarification_turns
            if max_clarification_turns is not None
            else int(os.getenv("MAX_CLARIFICATION_TURNS", "8"))
        )
        if not 1 <= maximum <= 50:
            raise ValueError("max_clarification_turns must be between 1 and 50")
        self.ttl_seconds = ttl_seconds
        self.max_clarification_turns = maximum
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._drafts: dict[str, DraftState] = {}
        self._lock = RLock()

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _purge_expired_locked(self, now: datetime) -> int:
        expired = [
            conversation_id
            for conversation_id, state in self._drafts.items()
            if state.expires_at <= now
        ]
        for conversation_id in expired:
            self._drafts.pop(conversation_id, None)
        return len(expired)

    def create(
        self,
        *,
        conversation_id: str,
        draft: AssessmentDraft,
        missing_fields: list[str],
        pending_question: str | None,
        clarification_turns: int = 0,
    ) -> DraftState:
        now = self._now()
        if clarification_turns > self.max_clarification_turns:
            raise DraftTurnLimit(conversation_id)
        with self._lock:
            self._purge_expired_locked(now)
            if conversation_id in self._drafts:
                raise ValueError(f"draft already exists: {conversation_id}")
            state = DraftState(
                conversation_id=conversation_id,
                draft=draft,
                missing_fields=missing_fields,
                pending_question=pending_question,
                clarification_turns=clarification_turns,
                confirmed=False,
                created_at=now,
                expires_at=now + self._ttl,
            )
            self._drafts[conversation_id] = state
            return state

    def get(self, conversation_id: str) -> DraftState:
        now = self._now()
        with self._lock:
            state = self._drafts.get(conversation_id)
            if state is None:
                raise DraftNotFound(conversation_id)
            if state.expires_at <= now:
                self._drafts.pop(conversation_id, None)
                raise DraftExpired(conversation_id)
            return state

    def update(self, state: DraftState) -> DraftState:
        now = self._now()
        with self._lock:
            current = self._drafts.get(state.conversation_id)
            if current is None:
                raise DraftNotFound(state.conversation_id)
            if current.expires_at <= now:
                self._drafts.pop(state.conversation_id, None)
                raise DraftExpired(state.conversation_id)
            if state.clarification_turns > self.max_clarification_turns:
                raise DraftTurnLimit(state.conversation_id)
            updated = state.model_copy(
                update={
                    "created_at": current.created_at,
                    "expires_at": now + self._ttl,
                }
            )
            self._drafts[state.conversation_id] = updated
            return updated

    def delete(self, conversation_id: str) -> None:
        with self._lock:
            if conversation_id not in self._drafts:
                raise DraftNotFound(conversation_id)
            self._drafts.pop(conversation_id, None)

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked(self._now())

    def __len__(self) -> int:
        with self._lock:
            return len(self._drafts)
