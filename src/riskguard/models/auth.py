"""Authentication contracts for the optional account mode."""

from __future__ import annotations

from pydantic import Field

from riskguard.auth.validation import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    USERNAME_PATTERN_TEXT,
)
from riskguard.models.assessment import ContractModel


class RegisterRequest(ContractModel):
    username: str = Field(
        min_length=USERNAME_MIN_LENGTH,
        max_length=USERNAME_MAX_LENGTH,
        pattern=USERNAME_PATTERN_TEXT,
    )
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )


class LoginRequest(ContractModel):
    username: str = Field(
        min_length=USERNAME_MIN_LENGTH,
        max_length=USERNAME_MAX_LENGTH,
        pattern=USERNAME_PATTERN_TEXT,
    )
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )


class AuthUser(ContractModel):
    user_id: str = Field(min_length=1)
    username: str = Field(min_length=1)


class AuthTokenResponse(ContractModel):
    user_id: str = Field(min_length=1)
    username: str = Field(min_length=1)
    token: str = Field(min_length=1)
    expires_at: str = Field(min_length=1)


class AuthError(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
