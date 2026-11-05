"""Minimal HTTP client for DeepSeek's OpenAI-compatible chat API."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, Protocol

import httpx

from riskguard.agent.errors import LLMConfigurationError, LLMRequestError, LLMResponseError


class ChatModel(Protocol):
    def complete(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout_seconds: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    @classmethod
    def from_env(cls) -> "DeepSeekClient":
        return cls(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        )

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def complete(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise LLMConfigurationError("DEEPSEEK_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": list(messages),
            "temperature": 0,
        }
        if tools:
            payload["tools"] = list(tools)
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if response_format is not None:
            payload["response_format"] = response_format

        client = self._http_client or httpx.Client(timeout=self._timeout_seconds)
        try:
            response = client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMRequestError("DeepSeek request failed") from exc
        finally:
            if self._http_client is None:
                client.close()

        if not isinstance(data, dict) or not data.get("choices"):
            raise LLMResponseError("DeepSeek returned no choices")
        return data
