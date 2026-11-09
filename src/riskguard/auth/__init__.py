"""Authentication package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from riskguard.auth.service import AuthService, AuthServiceError
    from riskguard.auth.store import AuthStore, AuthStoreError, UsernameAlreadyExists

__all__ = [
    "AuthService",
    "AuthServiceError",
    "AuthStore",
    "AuthStoreError",
    "UsernameAlreadyExists",
]


def __getattr__(name: str) -> Any:
    if name in {"AuthService", "AuthServiceError"}:
        from riskguard.auth.service import AuthService, AuthServiceError

        return {
            "AuthService": AuthService,
            "AuthServiceError": AuthServiceError,
        }[name]
    if name in {"AuthStore", "AuthStoreError", "UsernameAlreadyExists"}:
        from riskguard.auth.store import (
            AuthStore,
            AuthStoreError,
            UsernameAlreadyExists,
        )

        return {
            "AuthStore": AuthStore,
            "AuthStoreError": AuthStoreError,
            "UsernameAlreadyExists": UsernameAlreadyExists,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
