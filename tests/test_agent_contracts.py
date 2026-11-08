from __future__ import annotations

import json
from pathlib import Path

from riskguard.agent.schemas import (
    AgentChatResponse,
    IntakeResponse,
)

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))


def test_m56_response_contracts_include_turn_budget_fields() -> None:
    intake_contract = _load("agent_intake.schema.json")
    chat_contract = _load("agent_chat.schema.json")

    intake_properties = intake_contract["$defs"]["IntakeResponse"]["properties"]
    chat_properties = chat_contract["$defs"]["AgentChatResponse"]["properties"]
    required_fields = {
        "clarification_turns",
        "max_clarification_turns",
        "remaining_clarification_turns",
    }

    assert required_fields <= intake_properties.keys()
    assert required_fields <= chat_properties.keys()
    assert "clarification_limit" in intake_properties["status"]["enum"]
    assert "clarification_limit" in chat_properties["status"]["enum"]
    assert intake_properties.keys() == IntakeResponse.model_json_schema()["properties"].keys()
    assert chat_properties.keys() == AgentChatResponse.model_json_schema()["properties"].keys()


def test_conversation_contract_uses_bounded_turn_and_memory_metadata() -> None:
    chat_contract = _load("agent_chat.schema.json")
    conversation = chat_contract["$defs"]["ConversationState"]
    properties = conversation["properties"]

    assert "last_tool" in properties
    assert "pending_question" in properties
    assert properties["clarification_turns"]["maximum"] == 50


def test_clarification_limit_response_is_valid_contract_data() -> None:
    intake = IntakeResponse(
        conversation_id="conv_limit",
        status="clarification_limit",
        reply=(
            "我已经记录了你目前提供的信息。为了避免反复追问，"
            "你可以改用结构化表单继续补充，或者点击重新开始。"
        ),
        clarification_turns=8,
        max_clarification_turns=8,
        remaining_clarification_turns=0,
    )
    chat = AgentChatResponse(
        conversation_id="conv_limit",
        status="clarification_limit",
        reply=intake.reply,
        clarification_turns=8,
        max_clarification_turns=8,
        remaining_clarification_turns=0,
    )

    assert intake.status == "clarification_limit"
    assert chat.status == "clarification_limit"