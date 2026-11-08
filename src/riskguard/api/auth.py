"""Authentication API router."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from riskguard.auth import AuthService, AuthServiceError
from riskguard.models.auth import (
    AuthTokenResponse,
    AuthUser,
    LoginRequest,
    RegisterRequest,
)

bearer_scheme = HTTPBearer(auto_error=False)


def create_auth_router(auth_service: AuthService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

    def current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    ) -> AuthUser:
        if credentials is None:
            raise AuthServiceError(
                "AUTH_REQUIRED",
                "请先登录后再访问该功能。",
                status_code=401,
            )
        return auth_service.authenticate_token(credentials.credentials)

    def token_value(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    ) -> str:
        if credentials is None:
            raise AuthServiceError(
                "AUTH_REQUIRED",
                "请先登录后再访问该功能。",
                status_code=401,
            )
        return credentials.credentials

    @router.post(
        "/register",
        response_model=AuthTokenResponse,
        status_code=201,
    )
    def register(payload: RegisterRequest) -> AuthTokenResponse:
        return auth_service.register(payload.username, payload.password)

    @router.post("/login", response_model=AuthTokenResponse)
    def login(payload: LoginRequest) -> AuthTokenResponse:
        return auth_service.login(payload.username, payload.password)

    @router.post("/logout")
    def logout(token: str = Depends(token_value)) -> dict[str, str]:
        auth_service.logout(token)
        return {"status": "ok"}

    @router.get("/me", response_model=AuthUser)
    def me(user: AuthUser = Depends(current_user)) -> AuthUser:
        return user

    return router
