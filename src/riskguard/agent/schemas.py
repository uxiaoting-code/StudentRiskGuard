"""M4 natural-language intake and chat contracts.

These models describe temporary intake and conversation state. They are kept
separate from the frozen ``AssessmentRequest`` contract so missing values and
non-assessment chat turns never weaken M0 validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from riskguard.models.agent import (
    AgentError,
    Explanation,
    FIXED_BOUNDARY_NOTICE,
    ToolActivity,
)
from riskguard.models.memory import (
    AssessmentDraft,
    DebtDraft,
    DraftState,
    ExtractionResult,
    ExtractionStatus,
    IncomeDraft,
    RecurringSubscriptionDraft,
    ScenarioDraft,
)
from riskguard.models.assessment import (
    AssessmentRequest,
    AssessmentResult,
    BehaviorProfile,
    ContractModel,
    RiskLevel,
)

ExtractionStatus = Literal["complete", "needs_more_info", "invalid"]
IntakeStatus = Literal[
    "needs_more_info",
    "ready_for_confirmation",
    "clarification_limit",
    "invalid",
]
IntentName = Literal[
    "assessment_intake",
    "clarification",
    "risk_explanation",
    "education",
    "scenario_simulation",
    "out_of_scope",
]
ChatStatus = Literal[
    "needs_more_info",
    "ready_for_confirmation",
    "education_answer",
    "completed",
    "out_of_scope",
    "clarification_limit",
    "error",
]
ReviewStatus = Literal["pending", "approved"]


class NaturalLanguageIntakeRequest(ContractModel):
    """One turn of natural-language intake."""

    conversation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    message: str = Field(min_length=1, max_length=4000)


class AgentChatRequest(ContractModel):
    """Unified conversational Agent request."""

    conversation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    message: str = Field(min_length=1, max_length=4000)


class ConfirmIntakeRequest(ContractModel):
    """Optional user-corrected request used when confirming a draft."""

    assessment_request: AssessmentRequest | None = None


class ScenarioExtractionResult(ContractModel):
    status: ExtractionStatus
    scenario: ScenarioDraft | None = None
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    question: str | None = Field(default=None, max_length=500)


class ScenarioSimulationResult(ContractModel):
    scenario_id: str = Field(min_length=1)
    base_assessment: AssessmentResult
    scenario_assessment: AssessmentResult
    monthly_payment_delta: float
    monthly_surplus_delta: float
    risk_score_delta: int
    risk_level_before: RiskLevel
    risk_level_after: RiskLevel


class EducationCard(ContractModel):
    topic_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)
    allowed_actions: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = "pending"


class EducationAnswer(ContractModel):
    answer: str = Field(min_length=1, max_length=1200)
    topic_ids: list[str] = Field(min_length=1)
    boundary_notice: Literal[
        "本结果仅供金融教育与个人负债压力自查参考，不构成信贷审批、授信、放款或投资建议。"
    ] = FIXED_BOUNDARY_NOTICE
    review_status: ReviewStatus = "pending"


class IntakeResponse(ContractModel):
    conversation_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    status: IntakeStatus
    reply: str = Field(min_length=1)
    missing_fields: list[str] = Field(default_factory=list)
    clarification_turns: int = Field(default=0, ge=0, le=50)
    max_clarification_turns: int = Field(default=8, ge=1, le=50)
    remaining_clarification_turns: int = Field(default=8, ge=0, le=50)
    preview: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class AgentChatResponse(ContractModel):
    conversation_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    status: ChatStatus
    reply: str = Field(min_length=1)
    missing_fields: list[str] = Field(default_factory=list)
    clarification_turns: int = Field(default=0, ge=0, le=50)
    max_clarification_turns: int = Field(default=8, ge=1, le=50)
    remaining_clarification_turns: int = Field(default=8, ge=0, le=50)
    preview: dict[str, Any] | None = None
    assessment: AssessmentResult | None = None
    explanation: Explanation | None = None
    education: EducationAnswer | None = None
    scenario: ScenarioSimulationResult | None = None
    tool_activity: list[ToolActivity] = Field(default_factory=list)
    review_status: ReviewStatus | None = None
    error: AgentError | None = None
