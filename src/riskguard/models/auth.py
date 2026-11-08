"""Authentication contracts for the optional account mode."""

from __future__ import annotations

from pydantic import Field

from riskguard.models.assessment import ContractModel


class RegisterRequest(ContractModel):
    username: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-z0-9_]+$",
    )
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(ContractModel):
    username: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-z0-9_]+$",
    )
    password: str = Field(min_length=8, max_length=128)


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
