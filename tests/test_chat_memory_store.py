from __future__ import annotations

from datetime import datetime, timedelta, timezone

from riskguard.services.chat_memory_store import ChatMemoryStore


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 11, 8, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def test_chat_memory_is_bounded_and_ordered() -> None:
    store = ChatMemoryStore(ttl_seconds=60, max_messages=2)

    store.append(
        "conv-1",
        role="user",
        content="第一条",
        intent="assessment_intake",
        topic="irr_real_cost",
        assessment_id="asm_test",
        answer_type="needs_more_info",
        tool="retrieve_education_topic",
    )
    store.append("conv-1", role="assistant", content="第二条")
    store.append("conv-1", role="user", content="第三条")

    state = store.get_optional("conv-1")
    assert state is not None
    assert [item.content for item in state.messages] == ["第二条", "第三条"]
    assert ChatMemoryStore.last_assistant_message(state) == "第二条"
    assert state.last_intent == "assessment_intake"
    assert state.last_topic == "irr_real_cost"
    assert state.last_assessment_id == "asm_test"
    assert state.last_answer_type == "needs_more_info"
    assert state.last_tool == "retrieve_education_topic"


def test_chat_memory_expires_and_deletes() -> None:
    clock = FakeClock()
    store = ChatMemoryStore(ttl_seconds=30, max_messages=4, clock=clock)
    store.append("conv-1", role="user", content="短期内容")
    clock.advance(31)

    assert store.get_optional("conv-1") is None

    store.append("conv-2", role="user", content="删除内容")
    store.delete("conv-2")
    assert not store.get_optional("conv-2")
def test_chat_memory_configuration_has_finite_bounds() -> None:
    for kwargs in (
        {"ttl_seconds": 0, "max_messages": 8},
        {"ttl_seconds": 86_401, "max_messages": 8},
        {"ttl_seconds": 1800, "max_messages": 0},
        {"ttl_seconds": 1800, "max_messages": 11},
    ):
        try:
            ChatMemoryStore(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"configuration should be rejected: {kwargs}")


def test_chat_memory_store_has_no_persistence_or_logging_paths() -> None:
    from pathlib import Path

    source_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "riskguard"
        / "services"
        / "chat_memory_store.py"
    )
    source = source_path.read_text(encoding="utf-8").lower()
    for forbidden in (
        "import sqlite",
        "from sqlite",
        "open(",
        "import logging",
        "logger.",
    ):
        assert forbidden not in source
