"""M4 Agent state machine: tool call -> deterministic result -> explanation."""

from __future__ import annotations

import json
import re
import time
from typing import Any
from uuid import uuid4

from riskguard.agent.deepseek import ChatModel
from riskguard.agent.errors import (
    ExplanationInvalid,
    LLMResponseError,
    ToolCallMissing,
)
from riskguard.agent.fallback import build_fallback_explanation
from riskguard.agent.prompts import build_explanation_messages, build_tool_messages
from riskguard.models import (
    AgentError,
    AgentResponse,
    AssessmentResult,
    Explanation,
    ToolActivity,
)
from riskguard.services import SessionExpired, SessionNotFound, SessionStore
from riskguard.tools import RUN_RISK_ASSESSMENT_TOOL, RUN_RISK_ASSESSMENT_TOOL_NAME, ToolExecutor

TOOL_CHOICE = {
    "type": "function",
    "function": {"name": RUN_RISK_ASSESSMENT_TOOL_NAME},
}


class AgentRunner:
    """Run a bounded two-turn DeepSeek workflow with deterministic fallback."""

    def __init__(
        self,
        *,
        session_store: SessionStore,
        tool_executor: ToolExecutor,
        llm_client: ChatModel,
        max_tool_call_attempts: int = 2,
    ) -> None:
        self._session_store = session_store
        self._tool_executor = tool_executor
        self._llm_client = llm_client
        self._max_tool_call_attempts = max_tool_call_attempts

    def assess(self, session_id: str) -> AgentResponse:
        # Validate before any model call. Session errors must propagate to API handlers.
        self._session_store.get(session_id)

        result: AssessmentResult | None = None
        tool_activity: list[ToolActivity] = []
        try:
            assistant_message, tool_call = self._request_tool_call(session_id)
            result, activity = self._execute_tool_call(
                tool_call,
                expected_session_id=session_id,
            )
            tool_activity.append(activity)
            explanation = self._generate_explanation(
                session_id=session_id,
                assistant_message=assistant_message,
                tool_result=result.model_dump(mode="json"),
            )
            self._validate_explanation(explanation, result)
            return AgentResponse(
                request_id=result.request_id,
                status="completed",
                degraded=False,
                tool_activity=tool_activity,
                assessment=result,
                explanation=explanation,
                error=None,
            )
        except (SessionNotFound, SessionExpired):
            raise
        except Exception as exc:
            return self._degraded_response(
                session_id=session_id,
                existing_result=result,
                existing_activity=tool_activity,
                reason=type(exc).__name__,
            )

    def _request_tool_call(
        self,
        session_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        messages = build_tool_messages(session_id)
        for _ in range(self._max_tool_call_attempts):
            response = self._llm_client.complete(
                messages=messages,
                tools=[RUN_RISK_ASSESSMENT_TOOL],
                tool_choice=TOOL_CHOICE,
            )
            choices = response.get("choices") if isinstance(response, dict) else None
            if not choices:
                raise LLMResponseError("DeepSeek returned no choices")
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise LLMResponseError("DeepSeek returned an invalid message")
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                continue
            tool_call = tool_calls[0]
            function = tool_call.get("function") if isinstance(tool_call, dict) else None
            if not isinstance(function, dict):
                raise LLMResponseError("DeepSeek returned an invalid tool call")
            if function.get("name") != RUN_RISK_ASSESSMENT_TOOL_NAME:
                raise LLMResponseError("DeepSeek called an unsupported tool")
            return message, tool_call
        raise ToolCallMissing("DeepSeek did not return run_risk_assessment")

    def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        *,
        expected_session_id: str,
    ) -> tuple[AssessmentResult, ToolActivity]:
        function = tool_call["function"]
        try:
            arguments = json.loads(function.get("arguments", "{}"))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ExplanationInvalid("tool arguments are not valid JSON") from exc
        if not isinstance(arguments, dict):
            raise ExplanationInvalid("tool arguments must be an object")

        if set(arguments) != {"session_id"}:
            raise ExplanationInvalid("tool arguments must contain only session_id")
        if arguments["session_id"] != expected_session_id:
            raise ExplanationInvalid("tool call does not target the current session")

        started = time.perf_counter()
        result = self._tool_executor.execute(
            RUN_RISK_ASSESSMENT_TOOL_NAME,
            {"session_id": expected_session_id},
        )
        return result, ToolActivity(
            tool=RUN_RISK_ASSESSMENT_TOOL_NAME,
            status="succeeded",
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            error_code=None,
        )

    def _generate_explanation(
        self,
        *,
        session_id: str,
        assistant_message: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> Explanation:
        messages = build_explanation_messages(
            session_id=session_id,
            assistant_message=assistant_message,
            tool_result=tool_result,
        )
        response = self._llm_client.complete(
            messages=messages,
            response_format={"type": "json_object"},
        )
        choices = response.get("choices") if isinstance(response, dict) else None
        if not choices:
            raise LLMResponseError("DeepSeek returned no explanation choices")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ExplanationInvalid("DeepSeek returned empty explanation")

        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return Explanation.model_validate_json(cleaned)
        except Exception as exc:
            raise ExplanationInvalid("explanation does not match schema") from exc

    def _validate_explanation(self, explanation: Explanation, result: AssessmentResult) -> None:
        allowed_dimensions = {item.id for item in result.risk.dimensions}
        if not {item.dimension_id for item in explanation.risk_sources} <= allowed_dimensions:
            raise ExplanationInvalid("risk source references an unknown dimension")
        narrative = " ".join(
            [
                explanation.summary,
                *[item.title + item.detail for item in explanation.risk_sources],
                *explanation.actions,
                *explanation.education,
                *explanation.questions_to_consider,
            ]
        )
        if re.search(r"\d", narrative):
            raise ExplanationInvalid("explanation must not restate numeric values")

    def _degraded_response(
        self,
        *,
        session_id: str,
        existing_result: AssessmentResult | None,
        existing_activity: list[ToolActivity],
        reason: str,
    ) -> AgentResponse:
        result = existing_result
        activity = list(existing_activity)
        try:
            if result is None:
                started = time.perf_counter()
                result = self._tool_executor.execute(
                    RUN_RISK_ASSESSMENT_TOOL_NAME,
                    {"session_id": session_id},
                )
                activity.append(
                    ToolActivity(
                        tool=RUN_RISK_ASSESSMENT_TOOL_NAME,
                        status="succeeded",
                        latency_ms=round((time.perf_counter() - started) * 1000, 2),
                        error_code=None,
                    )
                )
            return AgentResponse(
                request_id=result.request_id,
                status="degraded",
                degraded=True,
                tool_activity=activity,
                assessment=result,
                explanation=build_fallback_explanation(result),
                error=AgentError(
                    code="AGENT_DEGRADED",
                    message=f"智能解读已降级，确定性计算结果仍然可用。原因：{reason}",
                ),
            )
        except (SessionNotFound, SessionExpired):
            raise
        except Exception as exc:
            return AgentResponse(
                request_id=f"req_{uuid4().hex[:12]}",
                status="error",
                degraded=True,
                tool_activity=activity,
                assessment=None,
                explanation=None,
                error=AgentError(
                    code="AGENT_FALLBACK_FAILED",
                    message="确定性评估和智能解读均暂时不可用，请稍后重试。",
                ),
            )
