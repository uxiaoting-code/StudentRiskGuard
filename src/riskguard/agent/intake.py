"""M4-A natural-language intake orchestration.

The flow is intentionally bounded:

user message -> extraction LLM -> merge draft -> missing fields -> ask or
confirm -> create anonymous session -> existing AgentRunner -> deterministic tool.

Raw user text is used only for the extraction request and is not stored in the
draft store.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4


from riskguard.agent.deepseek import ChatModel
from riskguard.agent.prompts import build_extraction_messages
from riskguard.agent.runner import AgentRunner
from riskguard.agent.schemas import (
    AssessmentDraft,
    DebtDraft,
    DraftState,
    ExtractionResult,
    IncomeDraft,
    IntakeResponse,
    NaturalLanguageIntakeRequest,
    RecurringSubscriptionDraft,
)
from riskguard.models import AgentResponse, AssessmentRequest, BehaviorProfile
from riskguard.services import (
    ConversationExpired,
    ConversationNotFound,
    ConversationStore,
    DraftStore,
    SessionStore,
)


class IntakeNotReady(Exception):
    """Raised when confirmation is attempted before required fields exist."""


class IntakeService:
    """Run the bounded natural-language intake workflow."""

    def __init__(
        self,
        *,
        draft_store: DraftStore,
        session_store: SessionStore,
        agent_runner: AgentRunner,
        llm_client: ChatModel,
        conversation_store: ConversationStore | None = None,
        max_clarification_turns: int = 3,
    ) -> None:
        self._draft_store = draft_store
        self._session_store = session_store
        self._agent_runner = agent_runner
        self._llm_client = llm_client
        self._conversation_store = conversation_store
        self._max_clarification_turns = max_clarification_turns

    def submit(self, payload: NaturalLanguageIntakeRequest) -> IntakeResponse:
        """Extract one turn and return a question, an invalid result, or a preview."""

        existing: DraftState | None = None
        if payload.conversation_id is not None:
            existing = self._draft_store.get(payload.conversation_id)

        conversation_id = (
            existing.conversation_id if existing is not None else self._new_conversation_id()
        )
        current_turn = 1 if existing is None else existing.clarification_turns + 1
        if current_turn > self._max_clarification_turns:
            return IntakeResponse(
                conversation_id=conversation_id,
                status="invalid",
                reply="本次信息补全已达到最大轮次，请重新开始或改用结构化表单填写。",
                missing_fields=existing.missing_fields if existing is not None else [],
                warnings=["MAX_CLARIFICATION_TURNS_REACHED"],
            )

        try:
            extraction = self._extract(
                user_message=payload.message,
                existing_draft=existing.draft if existing is not None else None,
            )
        except Exception:
            # Do not expose model internals or raw user text in the response.
            extraction = ExtractionResult(
                status="invalid",
                draft=None,
                warnings=["本次自然语言解析暂时不可用，请重新描述或改用结构化表单。"],
            )

        if extraction.status == "invalid":
            state = self._save_state(
                existing=existing,
                conversation_id=conversation_id,
                draft=existing.draft if existing is not None else AssessmentDraft(),
                missing_fields=existing.missing_fields if existing is not None else [],
                pending_question=None,
                turn=current_turn,
            )
            return IntakeResponse(
                conversation_id=state.conversation_id,
                status="invalid",
                reply="暂时无法可靠解析这段描述，请补充更明确的金额、期数和利率信息。",
                missing_fields=state.missing_fields,
                warnings=extraction.warnings or ["EXTRACTION_INVALID"],
            )

        if extraction.draft is None:
            state = self._save_state(
                existing=existing,
                conversation_id=conversation_id,
                draft=existing.draft if existing is not None else AssessmentDraft(),
                missing_fields=existing.missing_fields if existing is not None else [],
                pending_question=None,
                turn=current_turn,
            )
            return IntakeResponse(
                conversation_id=state.conversation_id,
                status="invalid",
                reply="没有提取到可用于评估的结构化信息，请重新描述。",
                missing_fields=state.missing_fields,
                warnings=["EXTRACTION_EMPTY"],
            )

        merged_draft = self._merge_drafts(
            existing.draft if existing is not None else AssessmentDraft(),
            extraction.draft,
        )
        missing_fields = self._collect_missing_fields(merged_draft)

        if self._has_invalid_total_income(merged_draft):
            state = self._save_state(
                existing=existing,
                conversation_id=conversation_id,
                draft=merged_draft,
                missing_fields=["income.positive_total"],
                pending_question="请确认你的生活费或兼职收入，当前总收入不能为零。",
                turn=current_turn,
            )
            return IntakeResponse(
                conversation_id=state.conversation_id,
                status="invalid",
                reply="当前收入信息不合法：生活费与兼职收入合计必须大于零。",
                missing_fields=state.missing_fields,
                warnings=["INVALID_TOTAL_INCOME"],
            )

        if missing_fields:
            question = extraction.question or self._build_question(missing_fields)
            state = self._save_state(
                existing=existing,
                conversation_id=conversation_id,
                draft=merged_draft,
                missing_fields=missing_fields,
                pending_question=question,
                turn=current_turn,
            )
            return IntakeResponse(
                conversation_id=state.conversation_id,
                status="needs_more_info",
                reply=question,
                missing_fields=missing_fields,
                preview=self._preview(merged_draft),
                warnings=extraction.warnings,
            )

        state = self._save_state(
            existing=existing,
            conversation_id=conversation_id,
            draft=merged_draft,
            missing_fields=[],
            pending_question=None,
            turn=current_turn,
        )
        return IntakeResponse(
            conversation_id=state.conversation_id,
            status="ready_for_confirmation",
            reply="信息已整理完成，请确认以下内容后开始风险评估。",
            missing_fields=[],
            preview=self._preview(merged_draft),
            warnings=extraction.warnings,
        )

    def confirm(
        self,
        conversation_id: str,
        assessment_request: AssessmentRequest | None = None,
    ) -> AgentResponse:
        """Confirm the draft, create a session and run the existing M4 chain."""

        state = self._draft_store.get(conversation_id)
        if assessment_request is not None:
            # A user-edited preview is allowed to fill gaps in the draft, but it
            # still has to pass the frozen AssessmentRequest validation below.
            request_payload = assessment_request.model_dump(mode="json")
        else:
            missing_fields = self._collect_missing_fields(state.draft)
            if missing_fields:
                raise IntakeNotReady(",".join(missing_fields))
            request_payload = self._draft_to_request_payload(state.draft)

        # The backend owns the anonymous session id. Do not trust an id supplied
        # by an edited preview.
        request_payload["session_id"] = f"anon_{uuid4().hex[:12]}"
        request = AssessmentRequest.model_validate(request_payload)
        self._session_store.create(request)

        response = self._agent_runner.assess(request.session_id)
        self._remember_assessment(conversation_id, request.session_id, response)
        self._draft_store.delete(conversation_id)
        return response

    def _remember_assessment(
        self,
        conversation_id: str,
        session_id: str,
        response: AgentResponse,
    ) -> None:
        if self._conversation_store is None:
            return
        assessment_id = response.assessment.assessment_id if response.assessment else None
        try:
            self._conversation_store.get(conversation_id)
            self._conversation_store.update(
                conversation_id,
                session_id=session_id,
                current_intent="risk_explanation",
                last_assessment_id=assessment_id,
                last_tool="run_risk_assessment",
                last_answer_type="assessment",
            )
        except (ConversationNotFound, ConversationExpired):
            self._conversation_store.create(
                conversation_id=conversation_id,
                session_id=session_id,
                current_intent="risk_explanation",
            )
            self._conversation_store.update(
                conversation_id,
                last_assessment_id=assessment_id,
                last_tool="run_risk_assessment",
                last_answer_type="assessment",
            )

    def _extract(
        self,
        *,
        user_message: str,
        existing_draft: AssessmentDraft | None,
    ) -> ExtractionResult:
        response = self._llm_client.complete(
            messages=build_extraction_messages(
                user_message=user_message,
                existing_draft=existing_draft,
            ),
            response_format={"type": "json_object"},
        )
        choices = response.get("choices") if isinstance(response, dict) else None
        if not choices:
            raise ValueError("extraction response has no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("extraction response is empty")

        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]
        return ExtractionResult.model_validate_json(cleaned)

    def _save_state(
        self,
        *,
        existing: DraftState | None,
        conversation_id: str,
        draft: AssessmentDraft,
        missing_fields: list[str],
        pending_question: str | None,
        turn: int,
    ) -> DraftState:
        if existing is None:
            return self._draft_store.create(
                conversation_id=conversation_id,
                draft=draft,
                missing_fields=missing_fields,
                pending_question=pending_question,
                clarification_turns=turn,
            )
        updated = existing.model_copy(
            update={
                "draft": draft,
                "missing_fields": missing_fields,
                "pending_question": pending_question,
                "clarification_turns": turn,
                "confirmed": False,
            }
        )
        return self._draft_store.update(updated)

    def _merge_drafts(
        self,
        existing: AssessmentDraft,
        incoming: AssessmentDraft,
    ) -> AssessmentDraft:
        income = self._merge_income(existing.income, incoming.income)
        debts, no_debts = self._merge_debts(existing, incoming)
        subscriptions = self._merge_subscriptions(
            existing.recurring_subscriptions,
            incoming.recurring_subscriptions,
        )
        behavior = existing.behavior
        if incoming.behavior is not None:
            behavior_data = (
                behavior.model_dump(mode="json") if behavior is not None else {}
            )
            behavior_data.update(incoming.behavior.model_dump(mode="json"))
            behavior = BehaviorProfile.model_validate(behavior_data)

        return AssessmentDraft(
            income=income,
            debts=debts,
            no_debts=no_debts,
            savings_balance=(
                incoming.savings_balance
                if incoming.savings_balance is not None
                else existing.savings_balance
            ),
            recurring_subscriptions=subscriptions,
            behavior=behavior,
            forecast_months=(
                incoming.forecast_months
                if incoming.forecast_months is not None
                else existing.forecast_months
            ),
        )

    @staticmethod
    def _merge_income(
        existing: IncomeDraft | None,
        incoming: IncomeDraft | None,
    ) -> IncomeDraft | None:
        if existing is None:
            return incoming
        if incoming is None:
            return existing
        data = existing.model_dump(mode="json")
        data.update(incoming.model_dump(mode="json", exclude_none=True))
        return IncomeDraft.model_validate(data)

    @staticmethod
    def _merge_debts(
        existing: AssessmentDraft,
        incoming: AssessmentDraft,
    ) -> tuple[list[DebtDraft] | None, bool | None]:
        if incoming.no_debts is True:
            return [], True
        if incoming.debts is None:
            return existing.debts, (
                incoming.no_debts
                if incoming.no_debts is not None
                else existing.no_debts
            )

        merged = list(existing.debts or [])
        for index, new_debt in enumerate(incoming.debts):
            target_index: int | None = None
            if new_debt.label:
                target_index = next(
                    (
                        i
                        for i, old_debt in enumerate(merged)
                        if old_debt.label == new_debt.label
                    ),
                    None,
                )
            if target_index is None and index < len(merged):
                target_index = index

            if target_index is None:
                merged.append(new_debt)
            else:
                data = merged[target_index].model_dump(mode="json")
                data.update(new_debt.model_dump(mode="json", exclude_none=True))
                merged[target_index] = DebtDraft.model_validate(data)

        no_debts = incoming.no_debts if incoming.no_debts is not None else existing.no_debts
        if merged:
            no_debts = False
        return merged, no_debts

    @staticmethod
    def _merge_subscriptions(
        existing: list[RecurringSubscriptionDraft] | None,
        incoming: list[RecurringSubscriptionDraft] | None,
    ) -> list[RecurringSubscriptionDraft] | None:
        if incoming is None:
            return existing
        merged = list(existing or [])
        for index, new_item in enumerate(incoming):
            target_index: int | None = None
            if new_item.label:
                target_index = next(
                    (
                        i
                        for i, old_item in enumerate(merged)
                        if old_item.label == new_item.label
                    ),
                    None,
                )
            if target_index is None and index < len(merged):
                target_index = index
            if target_index is None:
                merged.append(new_item)
            else:
                data = merged[target_index].model_dump(mode="json")
                data.update(new_item.model_dump(mode="json", exclude_none=True))
                merged[target_index] = RecurringSubscriptionDraft.model_validate(data)
        return merged

    @staticmethod
    def _collect_missing_fields(draft: AssessmentDraft) -> list[str]:
        missing: list[str] = []
        if draft.income is None:
            missing.extend(
                [
                    "income.monthly_disposable_allowance",
                    "income.monthly_part_time_income",
                ]
            )
        else:
            if draft.income.monthly_disposable_allowance is None:
                missing.append("income.monthly_disposable_allowance")
            if draft.income.monthly_part_time_income is None:
                missing.append("income.monthly_part_time_income")

        if draft.no_debts is not True:
            if draft.debts is None or not draft.debts:
                missing.append("debts")
            else:
                for index, debt in enumerate(draft.debts):
                    for field in (
                        "remaining_principal",
                        "monthly_payment",
                        "remaining_periods",
                        "nominal_apr",
                    ):
                        if getattr(debt, field) is None:
                            missing.append(f"debts[{index}].{field}")

        for index, subscription in enumerate(draft.recurring_subscriptions or []):
            if subscription.label is None:
                missing.append(f"recurring_subscriptions[{index}].label")
            if subscription.monthly_cost is None:
                missing.append(f"recurring_subscriptions[{index}].monthly_cost")

        return missing

    @staticmethod
    def _has_invalid_total_income(draft: AssessmentDraft) -> bool:
        if draft.income is None:
            return False
        if (
            draft.income.monthly_disposable_allowance is None
            or draft.income.monthly_part_time_income is None
        ):
            return False
        return (
            draft.income.monthly_disposable_allowance
            + draft.income.monthly_part_time_income
            <= 0
        )

    @staticmethod
    def _build_question(missing_fields: list[str]) -> str:
        labels = {
            "income.monthly_disposable_allowance": "每月稳定生活费",
            "income.monthly_part_time_income": "每月兼职收入（没有可以填 0）",
            "debts": "是否有分期负债；如果没有，请明确说“没有分期”",
            "remaining_principal": "分期剩余本金",
            "monthly_payment": "每月还款金额",
            "remaining_periods": "剩余期数",
            "nominal_apr": "名义利率（不清楚可以说明不清楚）",
            "label": "订阅名称",
            "monthly_cost": "订阅每月扣费金额",
        }
        human_labels: list[str] = []
        for field in missing_fields:
            tail = field.rsplit(".", 1)[-1]
            human_labels.append(labels.get(field) or labels.get(tail) or field)
        return "请补充以下信息：" + "、".join(human_labels[:6]) + "。"

    @staticmethod
    def _preview(draft: AssessmentDraft) -> dict[str, Any]:
        preview = draft.model_dump(mode="json", exclude_none=True)
        # This is an internal marker, not a field for the user-facing preview.
        preview.pop("no_debts", None)
        return preview

    @staticmethod
    def _draft_to_request_payload(draft: AssessmentDraft) -> dict[str, Any]:
        if draft.income is None:
            raise IntakeNotReady("income is missing")
        if (
            draft.income.monthly_disposable_allowance is None
            or draft.income.monthly_part_time_income is None
        ):
            raise IntakeNotReady("income fields are incomplete")

        debts: list[dict[str, Any]] = []
        if draft.no_debts is not True:
            for index, debt in enumerate(draft.debts or []):
                debts.append(
                    {
                        "id": f"debt_{index + 1}",
                        "label": debt.label or f"分期{index + 1}",
                        "remaining_principal": debt.remaining_principal,
                        "monthly_payment": debt.monthly_payment,
                        "remaining_periods": debt.remaining_periods,
                        "nominal_apr": debt.nominal_apr,
                    }
                )

        payload: dict[str, Any] = {
            "session_id": "placeholder",
            "income": {
                "monthly_disposable_allowance": draft.income.monthly_disposable_allowance,
                "monthly_part_time_income": draft.income.monthly_part_time_income,
            },
            "debts": debts,
        }
        if draft.savings_balance is not None:
            payload["savings_balance"] = draft.savings_balance
        if draft.recurring_subscriptions is not None:
            payload["recurring_subscriptions"] = [
                item.model_dump(mode="json", exclude_none=True)
                for item in draft.recurring_subscriptions
            ]
        if draft.behavior is not None:
            payload["behavior"] = draft.behavior.model_dump(mode="json")
        if draft.forecast_months is not None:
            payload["forecast_months"] = draft.forecast_months
        return payload

    @staticmethod
    def _new_conversation_id() -> str:
        return f"conv_{uuid4().hex[:12]}"
