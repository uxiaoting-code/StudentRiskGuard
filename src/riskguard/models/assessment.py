"""Pydantic v2 contracts for deterministic assessment data.

These models mirror the frozen JSON Schemas in ``contracts/``. They intentionally
contain no scoring or financial formulas; calculation belongs to M2.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RiskLevel = Literal["低风险", "关注", "中风险", "高风险"]
RiskDimensionId = Literal[
    "debt_to_income",
    "debt_stack",
    "real_cost",
    "behavior_resilience",
]
IrrStatus = Literal["ok", "unavailable"]


class ContractModel(BaseModel):
    """Base model that rejects fields outside the frozen contract."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class Income(ContractModel):
    monthly_disposable_allowance: float = Field(ge=0, le=1_000_000)
    monthly_part_time_income: float = Field(ge=0, le=1_000_000)

    @model_validator(mode="after")
    def require_positive_total_income(self) -> "Income":
        if self.monthly_disposable_allowance + self.monthly_part_time_income <= 0:
            raise ValueError("income total must be greater than zero")
        return self


class Debt(ContractModel):
    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=30)
    remaining_principal: float = Field(gt=0, le=1_000_000)
    monthly_payment: float = Field(gt=0, le=100_000)
    remaining_periods: int = Field(ge=1, le=120)
    nominal_apr: float = Field(ge=0, le=1)


class RecurringSubscription(ContractModel):
    label: str = Field(min_length=1, description="订阅名称")
    monthly_cost: float = Field(gt=0, description="每月扣费金额，单位元")


class BehaviorProfile(ContractModel):
    """Self-reported behavior signals used only by the behavior dimension."""

    borrow_to_repay: bool = False
    strict_overdue_count: int = Field(default=0, ge=0, le=100)
    insufficient_months_last_3: int = Field(default=0, ge=0, le=3)
    income_drop_30_cannot_cover: bool = False
    financial_cognition_score: float | None = Field(default=None, ge=1, le=5)


class AssessmentRequest(ContractModel):
    session_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    income: Income
    debts: list[Debt] = Field(max_length=20)
    savings_balance: float = Field(default=0.0, ge=0)
    recurring_subscriptions: list[RecurringSubscription] = Field(default_factory=list)
    behavior: BehaviorProfile = Field(default_factory=BehaviorProfile)
    forecast_months: int = Field(default=12, ge=1, le=36)

    @model_validator(mode="after")
    def require_unique_debt_ids(self) -> "AssessmentRequest":
        debt_ids = [debt.id for debt in self.debts]
        if len(debt_ids) != len(set(debt_ids)):
            raise ValueError("debt ids must be unique within a request")
        return self


class AssessmentMetrics(ContractModel):
    income_total: float = Field(ge=0)
    monthly_payment_total: float = Field(ge=0)
    debt_to_income_ratio: float = Field(ge=0)
    remaining_debt_total: float = Field(ge=0)
    debt_count: int = Field(ge=0)
    monthly_surplus: float
    surplus_ratio: float


class IrrResult(ContractModel):
    debt_id: str = Field(min_length=1)
    monthly_irr: float | None = None
    annualized_irr: float | None = None
    status: IrrStatus
    assumption: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_values_only_for_solved_irr(self) -> "IrrResult":
        if self.status == "ok" and (
            self.monthly_irr is None or self.annualized_irr is None
        ):
            raise ValueError("solved IRR requires monthly_irr and annualized_irr")
        if self.status == "unavailable" and (
            self.monthly_irr is not None or self.annualized_irr is not None
        ):
            raise ValueError("unavailable IRR must not contain guessed values")
        return self


class RiskDimension(ContractModel):
    id: RiskDimensionId
    raw_value: float
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0)


class RiskAssessment(ContractModel):
    score: int = Field(ge=0, le=100)
    level: RiskLevel
    dimensions: list[RiskDimension] = Field(min_length=4, max_length=4)
    top_contributors: list[str] = Field(min_length=1, max_length=3)

    @field_validator("top_contributors")
    @classmethod
    def require_unique_contributors(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("top_contributors must be unique")
        return values

    @model_validator(mode="after")
    def require_all_dimensions_once(self) -> "RiskAssessment":
        ids = [dimension.id for dimension in self.dimensions]
        if len(ids) != len(set(ids)):
            raise ValueError("risk dimensions must be unique")
        if not set(self.top_contributors).issubset(set(ids)):
            raise ValueError("top_contributors must reference known dimensions")
        return self


class CashflowPoint(ContractModel):
    month_index: int = Field(ge=1)
    income: float = Field(ge=0)
    debt_payment: float = Field(ge=0)
    surplus: float
    cumulative_surplus: float


class AssessmentAssumptions(ContractModel):
    currency: Literal["CNY"]
    income_constant: bool
    forecast_months: int = Field(ge=1, le=36)


class AssessmentResult(ContractModel):
    assessment_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    parameter_version: str = Field(min_length=1)
    metrics: AssessmentMetrics
    irr_results: list[IrrResult] = Field(max_length=20)
    risk: RiskAssessment
    cashflow_series: list[CashflowPoint] = Field(min_length=1, max_length=36)
    warnings: list[str]
    assumptions: AssessmentAssumptions

    @model_validator(mode="after")
    def require_matching_forecast_length(self) -> "AssessmentResult":
        if len(self.cashflow_series) != self.assumptions.forecast_months:
            raise ValueError("cashflow_series length must equal assumptions.forecast_months")
        return self
