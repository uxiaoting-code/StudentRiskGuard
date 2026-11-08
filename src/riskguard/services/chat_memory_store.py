"""Bounded, ephemeral chat memory for the task-oriented Agent."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable

from riskguard.models.memory import ChatMemoryState, MemoryMessage


class ChatMemoryStore:
    """Process-memory only short-term conversation buffer.

    This store is never serialized to disk, SQLite, logs, CSV, or localStorage.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int | None = None,
        max_messages: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else int(
            os.getenv("CHAT_MEMORY_TTL_SECONDS", "1800")
        )
        maximum = max_messages if max_messages is not None else int(
            os.getenv("CHAT_MEMORY_MAX_MESSAGES", "8")
        )
        if not 1 <= ttl <= 86_400:
            raise ValueError("ttl_seconds must be between 1 and 86400")
        if not 1 <= maximum <= 10:
            raise ValueError("max_messages must be between 1 and 10")
        self.ttl_seconds = ttl
        self.max_messages = maximum
        self._ttl = timedelta(seconds=ttl)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._states: dict[str, ChatMemoryState] = {}
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

    def get_optional(self, conversation_id: str) -> ChatMemoryState | None:
        now = self._now()
        with self._lock:
            state = self._states.get(conversation_id)
            if state is None:
                return None
            if state.expires_at <= now:
                self._states.pop(conversation_id, None)
                return None
            return state

    def append(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str,
        intent: str | None = None,
        topic: str | None = None,
        assessment_id: str | None = None,
        answer_type: str | None = None,
        tool: str | None = None,
    ) -> ChatMemoryState:
        now = self._now()
        with self._lock:
            current = self._states.get(conversation_id)
            if current is None or current.expires_at <= now:
                current = ChatMemoryState(
                    conversation_id=conversation_id,
                    messages=[],
                    created_at=now,
                    expires_at=now + self._ttl,
                )
            messages = list(current.messages)
            messages.append(
                MemoryMessage(role=role, content=content, created_at=now)
            )
            messages = messages[-self.max_messages :]
            updated = current.model_copy(
                update={
                    "messages": messages,
                    "last_intent": intent or current.last_intent,
                    "last_topic": topic or current.last_topic,
                    "last_assessment_id": assessment_id or current.last_assessment_id,
                    "last_answer_type": answer_type or current.last_answer_type,
                    "last_tool": tool or current.last_tool,
                    "expires_at": now + self._ttl,
                }
            )
            self._states[conversation_id] = updated
            return updated

    @staticmethod
    def last_assistant_message(state: ChatMemoryState | None) -> str | None:
        if state is None:
            return None
        for message in reversed(state.messages):
            if message.role == "assistant":
                return message.content
        return None

    def delete(self, conversation_id: str) -> None:
        with self._lock:
            self._states.pop(conversation_id, None)

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked(self._now())

    def __len__(self) -> int:
        with self._lock:
            return len(self._states)
