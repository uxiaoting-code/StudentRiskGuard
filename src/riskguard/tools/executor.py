"""Server-side execution of Agent tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from riskguard.models import AssessmentResult
from riskguard.services import AssessmentService
from riskguard.tools.definitions import (
    RUN_RISK_ASSESSMENT_TOOL_NAME,
    TOOL_NAMES,
    RunRiskAssessmentArguments,
)


class ToolError(Exception):
    """Base error for tool execution."""


class ToolNotFound(ToolError):
    pass


class ToolArgumentError(ToolError):
    pass


class ToolExecutor:
    """Execute only explicitly registered tools.

    Tool arguments intentionally contain only IDs. Raw financial details stay in
    the server-side session store and are never exposed to the LLM.
    """

    def __init__(self, assessment_service: AssessmentService) -> None:
        self._assessment_service = assessment_service

    @property
    def tool_names(self) -> frozenset[str]:
        return TOOL_NAMES

    def execute(self, tool_name: str, arguments: Mapping[str, Any]) -> AssessmentResult:
        if tool_name not in TOOL_NAMES:
            raise ToolNotFound(tool_name)
        if tool_name != RUN_RISK_ASSESSMENT_TOOL_NAME:
            raise ToolNotFound(tool_name)

        try:
            parsed = RunRiskAssessmentArguments.model_validate(dict(arguments))
        except ValidationError as exc:
            raise ToolArgumentError("run_risk_assessment requires only a valid session_id") from exc

        return self._assessment_service.assess_session(parsed.session_id)
