"""Pydantic v2 contracts for the Agent response envelope."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from riskguard.models.assessment import AssessmentResult, ContractModel

FIXED_BOUNDARY_NOTICE = (
    "本结果仅供金融教育与个人负债压力自查参考，"
    "不构成信贷审批、授信、放款或投资建议。"
)

AgentStatus = Literal["completed", "degraded", "needs_more_info", "error"]
ToolStatus = Literal["succeeded", "failed", "skipped"]


class RiskSource(ContractModel):
    dimension_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class Explanation(ContractModel):
    summary: str = Field(max_length=240)
    risk_sources: list[RiskSource] = Field(min_length=1, max_length=4)
    actions: list[str] = Field(min_length=2, max_length=5)
    education: list[str] = Field(min_length=1, max_length=4)
    questions_to_consider: list[str] = Field(min_length=1, max_length=4)
    boundary_notice: Literal[
        "本结果仅供金融教育与个人负债压力自查参考，不构成信贷审批、授信、放款或投资建议。"
    ]


class ToolActivity(ContractModel):
    tool: str = Field(min_length=1)
    status: ToolStatus
    latency_ms: float = Field(ge=0)
    error_code: str | None = None


class AgentError(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class AgentResponse(ContractModel):
    request_id: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    status: AgentStatus
    degraded: bool
    tool_activity: list[ToolActivity]
    assessment: AssessmentResult | None
    explanation: Explanation | None
    error: AgentError | None

    @model_validator(mode="after")
    def require_status_consistent_payload(self) -> "AgentResponse":
        if self.status == "completed":
            if self.degraded:
                raise ValueError("completed response cannot be degraded")
            if self.assessment is None or self.explanation is None:
                raise ValueError("completed response requires assessment and explanation")
        if self.status == "degraded":
            if not self.degraded:
                raise ValueError("degraded status requires degraded=True")
            if self.assessment is None or self.explanation is None:
                raise ValueError("degraded response requires assessment and fallback explanation")
        if self.status == "error" and self.error is None:
            raise ValueError("error status requires an error payload")
        return self
