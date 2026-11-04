"""API-only response and error models for the M3 session/tool layer."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionCreateResponse(ApiModel):
    session_id: str = Field(min_length=1, max_length=64)
    expires_at: datetime
    expires_in_seconds: int = Field(ge=1)


class SessionMetadata(ApiModel):
    session_id: str = Field(min_length=1, max_length=64)
    created_at: datetime
    expires_at: datetime
    debt_count: int = Field(ge=0)
    subscription_count: int = Field(ge=0)
    forecast_months: int = Field(ge=1, le=36)


class RunAssessmentRequest(ApiModel):
    session_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class ApiErrorDetail(ApiModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ApiErrorResponse(ApiModel):
    request_id: str = Field(min_length=1)
    error: ApiErrorDetail


class HealthResponse(ApiModel):
    status: Literal["ok"]
    service: Literal["studentriskguard-api"]
    version: str
