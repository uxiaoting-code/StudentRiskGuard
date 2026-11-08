"""M4-B scenario extraction and deterministic simulation service."""

from __future__ import annotations

import json
import os
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


class ScenarioDebtLimit(ScenarioServiceError):
    pass


class ScenarioService:
    def __init__(
        self,
        *,
        scenario_store: ScenarioStore,
        session_store: SessionStore,
        assessment_service: AssessmentService,
        llm_client: ChatModel,
        max_clarification_turns: int | None = None,
    ) -> None:
        self._scenario_store = scenario_store
        self._session_store = session_store
        self._assessment_service = assessment_service
        self._llm_client = llm_client
        maximum = (
            max_clarification_turns
            if max_clarification_turns is not None
            else int(os.getenv("MAX_CLARIFICATION_TURNS", "8"))
        )
        if not 1 <= maximum <= 50:
            raise ValueError("max_clarification_turns must be between 1 and 50")
        self.max_clarification_turns = maximum

    def extract_and_stage(
        self,
        message: str,
        *,
        conversation_id: str = "",
        session_id: str = "",
        existing_scenario: ScenarioDraft | None = None,
        existing_scenario_id: str | None = None,
        clarification_turns: int = 0,
        previous_question: str | None = None,
    ) -> tuple[ScenarioExtractionResult, str | None]:
        try:
            result = self._extract(
                message,
                existing_scenario=existing_scenario,
                previous_question=previous_question,
            )
        except Exception:
            return (
                ScenarioExtractionResult(
                    status="invalid",
                    warnings=["无法解析新增分期情景，请补充更明确的本金、月供、期数和利率。"],
                ),
                existing_scenario_id,
            )

        if result.status == "invalid":
            return result, existing_scenario_id

        incoming = result.scenario
        if incoming is None and existing_scenario is None:
            return result, existing_scenario_id
        scenario = self._merge_scenarios(existing_scenario, incoming)

        missing = self._missing_fields(scenario)
        if missing:
            turns = clarification_turns + 1 if existing_scenario_id else 0
            if existing_scenario_id is None:
                scenario_id = f"sc_{uuid4().hex[:12]}"
                self._scenario_store.create(
                    scenario_id,
                    scenario,
                    conversation_id=conversation_id,
                    session_id=session_id,
                    missing_fields=missing,
                    pending_question=result.question or self._question(missing),
                    clarification_turns=turns,
                )
            else:
                scenario_id = existing_scenario_id
                self._scenario_store.update(
                    scenario_id,
                    scenario,
                    missing_fields=missing,
                    pending_question=result.question or self._question(missing),
                    clarification_turns=turns,
                )
            return (
                ScenarioExtractionResult(
                    status="needs_more_info",
                    scenario=scenario,
                    missing_fields=missing,
                    warnings=result.warnings,
                    question=result.question
                    or self._question(missing),
                ),
                scenario_id,
            )

        if existing_scenario_id is None:
            scenario_id = f"sc_{uuid4().hex[:12]}"
            self._scenario_store.create(
                scenario_id,
                scenario,
                conversation_id=conversation_id,
                session_id=session_id,
                pending_question=None,
                clarification_turns=clarification_turns,
            )
        else:
            scenario_id = existing_scenario_id
            self._scenario_store.update(
                scenario_id,
                scenario,
                missing_fields=[],
                pending_question=None,
                clarification_turns=clarification_turns,
            )
        return (
            result.model_copy(
                update={
                    "status": "complete",
                    "scenario": scenario,
                    "missing_fields": [],
                    "warnings": result.warnings,
                    "question": None,
                }
            ),
            scenario_id,
        )

    def simulate(self, *, session_id: str, scenario_id: str) -> ScenarioSimulationResult:
        session = self._session_store.get(session_id)
        record = self._scenario_store.get(scenario_id)
        if record.session_id and record.session_id != session_id:
            raise ScenarioNotFound(scenario_id)
        scenario = record.scenario
        missing = list(record.missing_fields) or self._missing_fields(scenario)
        if missing:
            raise ScenarioNotReady(",".join(missing))
        if len(session.request.debts) >= 20:
            raise ScenarioDebtLimit("a request can contain at most 20 debts")

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
        result = ScenarioSimulationResult(
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
        self._scenario_store.delete(scenario_id)
        return result

    def _extract(
        self,
        message: str,
        *,
        existing_scenario: ScenarioDraft | None,
        previous_question: str | None,
    ) -> ScenarioExtractionResult:
        response = self._llm_client.complete(
            messages=build_scenario_extraction_messages(
                user_message=message,
                existing_scenario=(
                    existing_scenario.model_dump(mode="json", exclude_none=True)
                    if existing_scenario is not None
                    else None
                ),
                previous_question=previous_question,
            ),
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
    def _merge_scenarios(
        existing: ScenarioDraft | None,
        incoming: ScenarioDraft | None,
    ) -> ScenarioDraft:
        data = existing.model_dump(mode="json", exclude_none=True) if existing else {}
        if incoming is not None:
            data.update(incoming.model_dump(mode="json", exclude_none=True))
        return ScenarioDraft.model_validate(data)

    @staticmethod
    def _missing_fields(scenario: ScenarioDraft) -> list[str]:
        missing: list[str] = []
        for field in (
            "remaining_principal",
            "monthly_payment",
            "remaining_periods",
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
        }
        return "请补充" + "、".join(labels[item] for item in missing) + "。"
