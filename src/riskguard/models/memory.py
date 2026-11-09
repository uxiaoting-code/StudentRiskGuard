"""Contracts for bounded in-memory conversation memory."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from riskguard.models.assessment import BehaviorProfile, ContractModel


class MemoryMessage(ContractModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)
    created_at: datetime


class ChatMemoryState(ContractModel):
    conversation_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    messages: list[MemoryMessage] = Field(default_factory=list, max_length=10)
    last_intent: str | None = None
    last_topic: str | None = None
    last_assessment_id: str | None = None
    last_answer_type: str | None = None
    last_tool: str | None = None
    created_at: datetime
    expires_at: datetime


class ConversationState(ContractModel):
    conversation_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    active_task: Literal["intake", "scenario"] | None = None
    active_scenario_id: str | None = Field(default=None, min_length=1, max_length=64)
    current_intent: str | None = None
    last_topic: str | None = None
    last_assessment_id: str | None = None
    last_tool: str | None = None
    last_answer_type: str | None = None
    clarification_turns: int = Field(default=0, ge=0, le=50)
    pending_question: str | None = Field(default=None, max_length=500)
    created_at: datetime
    expires_at: datetime


class ScenarioDraft(ContractModel):
    label: str | None = Field(default=None, min_length=1, max_length=30)
    remaining_principal: float | None = Field(default=None, gt=0, le=1_000_000)
    monthly_payment: float | None = Field(default=None, gt=0, le=100_000)
    remaining_periods: int | None = Field(default=None, ge=1, le=120)
    nominal_apr: float | None = Field(default=None, ge=0, le=1)

ExtractionStatus = Literal["complete", "needs_more_info", "invalid"]


class IncomeDraft(ContractModel):
    monthly_disposable_allowance: float | None = Field(default=None, ge=0, le=1_000_000)
    monthly_part_time_income: float | None = Field(default=None, ge=0, le=1_000_000)


class DebtDraft(ContractModel):
    id: str | None = Field(default=None, min_length=1, max_length=32)
    label: str | None = Field(default=None, min_length=1, max_length=30)
    remaining_principal: float | None = Field(default=None, gt=0, le=1_000_000)
    total_remaining_repayment: float | None = Field(default=None, gt=0, le=1_000_000)
    final_payment: float | None = Field(default=None, gt=0, le=100_000)
    monthly_payment: float | None = Field(default=None, gt=0, le=100_000)
    remaining_periods: int | None = Field(default=None, ge=0, le=120)
    nominal_apr: float | None = Field(default=None, ge=0, le=1)
    nominal_apr_status: Literal["not_mentioned", "unknown", "provided"] | None = None
    derived_fields: list[str] = Field(default_factory=list)
    kind: Literal["unknown", "installment", "subscription"] | None = None
    settled: bool | None = None


class RecurringSubscriptionDraft(ContractModel):
    label: str | None = Field(default=None, min_length=1)
    monthly_cost: float | None = Field(default=None, gt=0)


class AssessmentDraft(ContractModel):
    income: IncomeDraft | None = None
    debts: list[DebtDraft] | None = None
    no_debts: bool | None = None
    savings_balance: float | None = Field(default=None, ge=0)
    recurring_subscriptions: list[RecurringSubscriptionDraft] | None = None
    behavior: BehaviorProfile | None = None
    forecast_months: int | None = Field(default=None, ge=1, le=36)


class ExtractionResult(ContractModel):
    status: ExtractionStatus
    draft: AssessmentDraft | None = None
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    question: str | None = Field(default=None, max_length=500)


class DraftState(ContractModel):
    conversation_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    draft: AssessmentDraft
    missing_fields: list[str] = Field(default_factory=list)
    pending_question: str | None = Field(default=None, max_length=500)
    current_debt_index: int | None = Field(default=None, ge=0)
    current_debt_label: str | None = Field(default=None, max_length=30)
    clarification_turns: int = Field(default=0, ge=0, le=50)
    confirmed: bool = False
    created_at: datetime
    expires_at: datetime
