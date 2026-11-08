"""Authentication service for optional account mode."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from riskguard.auth.security import hash_password, hash_token, new_token, verify_password
from riskguard.auth.store import AuthStore, UsernameAlreadyExists
from riskguard.models.auth import AuthTokenResponse, AuthUser


class AuthServiceError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class AuthService:
    def __init__(
        self,
        store: AuthStore | None = None,
        *,
        token_ttl_minutes: int | None = None,
    ) -> None:
        self.store = store or AuthStore()
        self.token_ttl_minutes = token_ttl_minutes or int(
            os.getenv("AUTH_TOKEN_TTL_MINUTES", "1440")
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def register(self, username: str, password: str) -> AuthTokenResponse:
        clean_username = username.strip()
        user_id = f"usr_{uuid4().hex[:16]}"
        try:
            user = self.store.create_user(
                user_id=user_id,
                username=clean_username,
                password_hash=hash_password(password),
                consent_version="auth-mvp-2026-11",
            )
        except UsernameAlreadyExists as exc:
            raise AuthServiceError(
                "USERNAME_TAKEN",
                "这个用户名已经被使用。",
                status_code=409,
            ) from exc
        return self._issue_token(user["user_id"], user["username"])

    def login(self, username: str, password: str) -> AuthTokenResponse:
        user = self.store.get_user_by_username(username.strip())
        if user is None or not verify_password(password, user["password_hash"]):
            raise AuthServiceError(
                "INVALID_CREDENTIALS",
                "用户名或密码错误。",
                status_code=401,
            )
        return self._issue_token(user["id"], user["username"])

    def authenticate_token(self, token: str) -> AuthUser:
        if not token:
            raise AuthServiceError("INVALID_TOKEN", "登录状态无效，请重新登录。", status_code=401)
        session = self.store.get_session_by_token_hash(hash_token(token))
        if session is None:
            raise AuthServiceError("INVALID_TOKEN", "登录状态无效，请重新登录。", status_code=401)
        expires_at = datetime.fromisoformat(session["expires_at"])
        if expires_at <= self._now():
            self.store.delete_session(hash_token(token))
            raise AuthServiceError("TOKEN_EXPIRED", "登录已过期，请重新登录。", status_code=401)
        return AuthUser(user_id=session["user_id"], username=session["username"])

    def logout(self, token: str) -> None:
        if token:
            self.store.delete_session(hash_token(token))

    def cleanup_expired_sessions(self) -> int:
        return self.store.delete_expired_sessions()

    def _issue_token(self, user_id: str, username: str) -> AuthTokenResponse:
        self.cleanup_expired_sessions()
        token = new_token()
        now = self._now()
        expires_at = now + timedelta(minutes=self.token_ttl_minutes)
        self.store.create_session(
            session_id=f"auth_{uuid4().hex[:16]}",
            user_id=user_id,
            token_hash=hash_token(token),
            created_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        return AuthTokenResponse(
            user_id=user_id,
            username=username,
            token=token,
            expires_at=expires_at.isoformat(),
        )
