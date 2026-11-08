"""In-memory conversation context store for M4-B.

Only structured state is retained. Raw user messages are not stored here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable

from riskguard.models.memory import ConversationState


class ConversationStoreError(Exception):
    pass


class ConversationNotFound(ConversationStoreError):
    pass


class ConversationExpired(ConversationStoreError):
    pass


class ConversationStore:
    """Thread-safe, TTL-limited conversation state store."""

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
        self._states: dict[str, ConversationState] = {}
        self._lock = RLock()

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _purge_expired_locked(self, now: datetime) -> int:
        expired = [
            conversation_id
            for conversation_id, state in self._states.items()
            if state.expires_at <= now
        ]
        for conversation_id in expired:
            self._states.pop(conversation_id, None)
        return len(expired)

    def create(
        self,
        *,
        conversation_id: str,
        session_id: str | None = None,
        current_intent: str | None = None,
        active_task: str | None = None,
        active_scenario_id: str | None = None,
    ) -> ConversationState:
        now = self._now()
        with self._lock:
            self._purge_expired_locked(now)
            if conversation_id in self._states:
                raise ValueError(f"conversation already exists: {conversation_id}")
            state = ConversationState(
                conversation_id=conversation_id,
                session_id=session_id,
                current_intent=current_intent,  # type: ignore[arg-type]
                active_task=active_task,  # type: ignore[arg-type]
                active_scenario_id=active_scenario_id,
                created_at=now,
                expires_at=now + self._ttl,
            )
            self._states[conversation_id] = state
            return state

    def get(self, conversation_id: str) -> ConversationState:
        now = self._now()
        with self._lock:
            state = self._states.get(conversation_id)
            if state is None:
                raise ConversationNotFound(conversation_id)
            if state.expires_at <= now:
                self._states.pop(conversation_id, None)
                raise ConversationExpired(conversation_id)
            return state

    def get_optional(self, conversation_id: str | None) -> ConversationState | None:
        if conversation_id is None:
            return None
        try:
            return self.get(conversation_id)
        except (ConversationNotFound, ConversationExpired):
            return None

    def update(
        self,
        conversation_id: str,
        *,
        session_id: str | None = None,
        current_intent: str | None = None,
        active_task: str | None = None,
        active_scenario_id: str | None = None,
        clear_active_task: bool = False,
        clear_active_scenario: bool = False,
        last_topic: str | None = None,
        last_assessment_id: str | None = None,
        last_tool: str | None = None,
        last_answer_type: str | None = None,
        clarification_turns: int | None = None,
        pending_question: str | None = None,
    ) -> ConversationState:
        now = self._now()
        with self._lock:
            current = self._states.get(conversation_id)
            if current is None:
                raise ConversationNotFound(conversation_id)
            if current.expires_at <= now:
                self._states.pop(conversation_id, None)
                raise ConversationExpired(conversation_id)
            # Only overwrite optional context when the caller provides a value.
            # pending_question is always assigned so a completed turn can clear
            # the previous question deterministically.
            updates: dict[str, object] = {
                "pending_question": pending_question,
                "expires_at": now + self._ttl,
            }
            if clear_active_task:
                updates["active_task"] = None
            elif active_task is not None:
                updates["active_task"] = active_task
            if clear_active_scenario:
                updates["active_scenario_id"] = None
            elif active_scenario_id is not None:
                updates["active_scenario_id"] = active_scenario_id
            for field_name, value in (
                ("session_id", session_id),
                ("current_intent", current_intent),
                ("last_topic", last_topic),
                ("last_assessment_id", last_assessment_id),
                ("last_tool", last_tool),
                ("last_answer_type", last_answer_type),
                ("clarification_turns", clarification_turns),
            ):
                if value is not None:
                    updates[field_name] = value
            updated = current.model_copy(update=updates)
            self._states[conversation_id] = updated
            return updated

    def delete(self, conversation_id: str) -> None:
        with self._lock:
            if conversation_id not in self._states:
                raise ConversationNotFound(conversation_id)
            self._states.pop(conversation_id, None)

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked(self._now())

    def __len__(self) -> int:
        with self._lock:
            return len(self._states)
