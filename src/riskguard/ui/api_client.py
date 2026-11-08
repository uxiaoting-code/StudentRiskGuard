"""HTTP client used by the Streamlit M5 UI."""

from __future__ import annotations

import os
from typing import Any

import httpx


class ApiClientError(Exception):
    """A user-displayable backend error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ApiClient:
    """Thin adapter over the existing FastAPI endpoints."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("RISKGUARD_API_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        self._http_client = http_client
        self.access_token: str | None = None

    def _client(self) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=60.0)

    @staticmethod
    def _response_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return "后端请求失败，请稍后重试。"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            detail = payload.get("detail")
            if detail:
                return "输入或请求不符合要求，请检查后重试。"
        return "后端请求失败，请稍后重试。"

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        include_auth: bool = True,
    ) -> Any:
        client = self._client()
        close_client = self._http_client is None
        headers: dict[str, str] = {}
        if include_auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            response = client.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers=headers,
            )
            response.raise_for_status()
            if response.status_code == 204 or not response.content:
                return None
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise ApiClientError(
                self._response_error(exc.response),
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiClientError("无法连接后端服务，请确认 FastAPI 已启动。") from exc
        finally:
            if close_client:
                client.close()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def create_session(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/sessions", json=request)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/sessions/{session_id}")

    def delete_session(self, session_id: str) -> None:
        self._request("DELETE", f"/api/v1/sessions/{session_id}")

    def assess(self, session_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/assessments",
            json={"session_id": session_id},
        )

    def agent_assess(self, session_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/agent/assess",
            json={"session_id": session_id},
        )

    def submit_intake(
        self,
        message: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": message}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return self._request("POST", "/api/v1/agent/intake", json=payload)

    def confirm_intake(self, conversation_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/agent/intake/{conversation_id}/confirm",
        )

    def chat(self, message: str, conversation_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": message}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return self._request("POST", "/api/v1/agent/chat", json=payload)

    def list_education_topics(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/api/v1/education/topics")
        return result if isinstance(result, list) else []


    def set_access_token(self, token: str | None) -> None:
        self.access_token = token

    def register(self, username: str, password: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/auth/register",
            json={"username": username, "password": password},
            include_auth=False,
        )

    def login(self, username: str, password: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/auth/login",
            json={"username": username, "password": password},
            include_auth=False,
        )

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/auth/me")

    def logout(self) -> dict[str, Any]:
        result = self._request("POST", "/api/v1/auth/logout")
        self.access_token = None
        return result or {"status": "ok"}
