"""Server-side execution of Agent tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from riskguard.models import AssessmentResult
from riskguard.services import AssessmentService
from riskguard.services.education_service import EducationService
from riskguard.services.scenario_service import ScenarioService
from riskguard.tools.definitions import (
    RETRIEVE_EDUCATION_TOPIC_TOOL_NAME,
    RUN_RISK_ASSESSMENT_TOOL_NAME,
    SIMULATE_NEW_INSTALLMENT_TOOL_NAME,
    TOOL_NAMES,
    RetrieveEducationTopicArguments,
    RunRiskAssessmentArguments,
    SimulateNewInstallmentArguments,
)


class ToolError(Exception):
    """Base error for tool execution."""


class ToolNotFound(ToolError):
    pass


class ToolArgumentError(ToolError):
    pass


class ToolExecutor:
    """Execute only explicitly registered tools.

    Tool arguments intentionally contain IDs only. Raw financial details stay in
    the server-side session store and are never exposed to the LLM.
    """

    def __init__(
        self,
        assessment_service: AssessmentService,
        *,
        education_service: EducationService | None = None,
        scenario_service: ScenarioService | None = None,
    ) -> None:
        self._assessment_service = assessment_service
        self._education_service = education_service
        self._scenario_service = scenario_service

    @property
    def tool_names(self) -> frozenset[str]:
        return TOOL_NAMES

    def execute(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        if tool_name not in TOOL_NAMES:
            raise ToolNotFound(tool_name)

        if tool_name == RUN_RISK_ASSESSMENT_TOOL_NAME:
            try:
                parsed = RunRiskAssessmentArguments.model_validate(dict(arguments))
            except ValidationError as exc:
                raise ToolArgumentError("run_risk_assessment requires only a valid session_id") from exc
            return self._assessment_service.assess_session(parsed.session_id)

        if tool_name == RETRIEVE_EDUCATION_TOPIC_TOOL_NAME:
            if self._education_service is None:
                raise ToolNotFound(tool_name)
            try:
                parsed = RetrieveEducationTopicArguments.model_validate(dict(arguments))
            except ValidationError as exc:
                raise ToolArgumentError("retrieve_education_topic requires a valid topic_id") from exc
            return self._education_service.get_topic(parsed.topic_id)

        if tool_name == SIMULATE_NEW_INSTALLMENT_TOOL_NAME:
            if self._scenario_service is None:
                raise ToolNotFound(tool_name)
            try:
                parsed = SimulateNewInstallmentArguments.model_validate(dict(arguments))
            except ValidationError as exc:
                raise ToolArgumentError("simulate_new_installment requires session_id and scenario_id") from exc
            return self._scenario_service.simulate(
                session_id=parsed.session_id,
                scenario_id=parsed.scenario_id,
            )

        raise ToolNotFound(tool_name)
