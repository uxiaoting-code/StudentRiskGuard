"""Tool definitions exposed to the interaction Agent in M4."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from riskguard.models.assessment import ContractModel


RUN_RISK_ASSESSMENT_TOOL_NAME = "run_risk_assessment"

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

TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (RUN_RISK_ASSESSMENT_TOOL,)
TOOL_NAMES = frozenset(
    definition["function"]["name"] for definition in TOOL_DEFINITIONS
)


class RunRiskAssessmentArguments(ContractModel):
    session_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
