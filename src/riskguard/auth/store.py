"""SQLite storage for accounts and authentication sessions only.

No financial fields, assessment payloads, or raw chat text are stored here.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


class AuthStoreError(Exception):
    pass


class UsernameAlreadyExists(AuthStoreError):
    pass


class AuthStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            configured = os.getenv("AUTH_DB_PATH")
            db_path = configured or (
                Path(__file__).resolve().parents[3] / "data" / "auth.db"
            )
        self.path = Path(db_path)
        self._initialized = False
        self._lock = RLock()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_schema(self) -> None:
        with self._lock:
            if self._initialized:
                return
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        password_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        consent_version TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_sessions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        token_hash TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)"
                )
                connection.commit()
            self._initialized = True

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        password_hash: str,
        consent_version: str,
    ) -> dict[str, Any]:
        self._ensure_schema()
        created_at = self._now()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (id, username, password_hash, created_at, consent_version)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, username, password_hash, created_at, consent_version),
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise UsernameAlreadyExists(username) from exc
        return {
            "user_id": user_id,
            "username": username,
            "created_at": created_at,
            "consent_version": consent_version,
        }

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, password_hash, created_at, consent_version FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, created_at, consent_version FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        created_at: str,
        expires_at: str,
    ) -> None:
        self._ensure_schema()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_sessions
                    (id, user_id, token_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, user_id, token_hash, created_at, expires_at),
            )
            connection.commit()

    def get_session_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.id, s.user_id, s.created_at, s.expires_at, u.username
                FROM auth_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
        return dict(row) if row is not None else None

    def delete_session(self, token_hash: str) -> None:
        self._ensure_schema()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE token_hash = ?",
                (token_hash,),
            )
            connection.commit()

    def delete_expired_sessions(self) -> int:
        self._ensure_schema()
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= ?",
                (now,),
            )
            connection.commit()
            return cursor.rowcount
