"""Tool definitions exposed to the StudentRiskGuard Agent."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from riskguard.models.assessment import ContractModel


RUN_RISK_ASSESSMENT_TOOL_NAME = "run_risk_assessment"
RETRIEVE_EDUCATION_TOPIC_TOOL_NAME = "retrieve_education_topic"
SIMULATE_NEW_INSTALLMENT_TOOL_NAME = "simulate_new_installment"

RUN_RISK_ASSESSMENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": RUN_RISK_ASSESSMENT_TOOL_NAME,
        "description": "对匿名会话执行确定性负债压力评估。模型不得自行计算任何数值。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["session_id"],
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "匿名会话 ID",
                }
            },
        },
    },
}

RETRIEVE_EDUCATION_TOPIC_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": RETRIEVE_EDUCATION_TOPIC_TOOL_NAME,
        "description": "读取审核中的金融教育卡片，只返回卡片内容。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["topic_id"],
            "properties": {
                "topic_id": {
                    "type": "string",
                    "description": "教育主题 ID",
                }
            },
        },
    },
}

SIMULATE_NEW_INSTALLMENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": SIMULATE_NEW_INSTALLMENT_TOOL_NAME,
        "description": "对当前会话执行新增分期情景模拟，不修改原始会话。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["session_id", "scenario_id"],
            "properties": {
                "session_id": {"type": "string"},
                "scenario_id": {"type": "string"},
            },
        },
    },
}

TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    RUN_RISK_ASSESSMENT_TOOL,
    RETRIEVE_EDUCATION_TOPIC_TOOL,
    SIMULATE_NEW_INSTALLMENT_TOOL,
)
TOOL_NAMES = frozenset(
    definition["function"]["name"] for definition in TOOL_DEFINITIONS
)


class RunRiskAssessmentArguments(ContractModel):
    session_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class RetrieveEducationTopicArguments(ContractModel):
    topic_id: str = Field(min_length=1, max_length=64)


class SimulateNewInstallmentArguments(ContractModel):
    session_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    scenario_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
