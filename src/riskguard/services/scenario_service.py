"""M4-B scenario extraction and deterministic simulation service."""

from __future__ import annotations

import json
import re
from uuid import uuid4

from riskguard.agent.deepseek import ChatModel
from riskguard.agent.prompts import build_scenario_extraction_messages
from riskguard.agent.schemas import ScenarioExtractionResult, ScenarioSimulationResult
from riskguard.models.memory import ScenarioDraft
from riskguard.models import AssessmentRequest, Debt
from riskguard.services import AssessmentService, ScenarioStore, SessionStore


class ScenarioServiceError(Exception):
    pass


class ScenarioNotReady(ScenarioServiceError):
    pass


class ScenarioService:
    def __init__(
        self,
        *,
        scenario_store: ScenarioStore,
        session_store: SessionStore,
        assessment_service: AssessmentService,
        llm_client: ChatModel,
    ) -> None:
        self._scenario_store = scenario_store
        self._session_store = session_store
        self._assessment_service = assessment_service
        self._llm_client = llm_client

    def extract_and_stage(self, message: str) -> tuple[ScenarioExtractionResult, str | None]:
        try:
            result = self._extract(message)
        except Exception:
            return (
                ScenarioExtractionResult(
                    status="invalid",
                    warnings=["无法解析新增分期情景，请补充更明确的本金、月供、期数和利率。"],
                ),
                None,
            )

        if result.status == "invalid" or result.scenario is None:
            return result, None

        missing = self._missing_fields(result.scenario)
        if missing:
            return (
                ScenarioExtractionResult(
                    status="needs_more_info",
                    scenario=result.scenario,
                    missing_fields=missing,
                    warnings=result.warnings,
                    question=result.question
                    or self._question(missing),
                ),
                None,
            )

        scenario_id = f"sc_{uuid4().hex[:12]}"
        self._scenario_store.create(scenario_id, result.scenario)
        return result, scenario_id

    def simulate(self, *, session_id: str, scenario_id: str) -> ScenarioSimulationResult:
        session = self._session_store.get(session_id)
        record = self._scenario_store.get(scenario_id)
        scenario = record.scenario
        missing = self._missing_fields(scenario)
        if missing:
            raise ScenarioNotReady(",".join(missing))

        scenario_request = session.request.model_copy(deep=True)
        next_index = len(scenario_request.debts) + 1
        scenario_request.debts.append(
            Debt(
                id=f"scenario_{next_index}",
                label=scenario.label or "新增分期",
                remaining_principal=scenario.remaining_principal,
                monthly_payment=scenario.monthly_payment,
                remaining_periods=scenario.remaining_periods,
                nominal_apr=scenario.nominal_apr,
            )
        )
        # Re-run the same M2 tool through the existing assessment service.
        base = self._assessment_service.assess(session.request)
        simulated = self._assessment_service.assess(scenario_request)
        return ScenarioSimulationResult(
            scenario_id=scenario_id,
            base_assessment=base,
            scenario_assessment=simulated,
            monthly_payment_delta=round(
                simulated.metrics.monthly_payment_total
                - base.metrics.monthly_payment_total,
                6,
            ),
            monthly_surplus_delta=round(
                simulated.metrics.monthly_surplus - base.metrics.monthly_surplus,
                6,
            ),
            risk_score_delta=simulated.risk.score - base.risk.score,
            risk_level_before=base.risk.level,
            risk_level_after=simulated.risk.level,
        )

    def _extract(self, message: str) -> ScenarioExtractionResult:
        response = self._llm_client.complete(
            messages=build_scenario_extraction_messages(user_message=message),
            response_format={"type": "json_object"},
        )
        choices = response.get("choices") if isinstance(response, dict) else None
        if not choices:
            raise ValueError("scenario response has no choices")
        message_data = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message_data.get("content") if isinstance(message_data, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("scenario response is empty")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]
        result = ScenarioExtractionResult.model_validate_json(cleaned)
        if result.status == "complete" and result.scenario is not None:
            missing = self._missing_fields(result.scenario)
            if missing:
                return ScenarioExtractionResult(
                    status="needs_more_info",
                    scenario=result.scenario,
                    missing_fields=missing,
                    warnings=result.warnings,
                    question=result.question or self._question(missing),
                )
        return result

    @staticmethod
    def _missing_fields(scenario: ScenarioDraft) -> list[str]:
        missing: list[str] = []
        for field in (
            "remaining_principal",
            "monthly_payment",
            "remaining_periods",
            "nominal_apr",
        ):
            if getattr(scenario, field) is None:
                missing.append(field)
        return missing

    @staticmethod
    def _question(missing: list[str]) -> str:
        labels = {
            "remaining_principal": "新增分期的本金",
            "monthly_payment": "新增分期的每月还款",
            "remaining_periods": "新增分期的期数",
            "nominal_apr": "新增分期的名义利率（不清楚可以说明不清楚）",
        }
        return "请补充" + "、".join(labels[item] for item in missing) + "。"
