"""M4-A natural-language intake orchestration.

The flow is intentionally bounded:

user message -> extraction LLM -> merge draft -> missing fields -> ask or
confirm -> create anonymous session -> existing AgentRunner -> deterministic tool.

Raw user text is used only for the extraction request and is not stored in the
draft store.
"""

from __future__ import annotations

import json
import os
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
    DraftExpired,
    DraftNotFound,
    DraftStore,
    SessionStore,
)

_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "俩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_CN_NUMBER_CHARS = "".join(_CN_DIGITS) + "".join(_CN_UNITS)
_UNKNOWN_TERMS = ("不知道", "不清楚", "没注意", "没告诉我", "忘了", "不记得")
_NO_VALUE_TERMS = ("没有", "没有哦", "无", "零")


def _parse_chinese_number(text: str) -> float | None:
    cleaned = "".join(char for char in text if char in _CN_DIGITS or char in _CN_UNITS)
    if not cleaned:
        return None

    total = 0
    section = 0
    number = 0
    for char in cleaned:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
            continue
        unit = _CN_UNITS[char]
        if unit == 10000:
            section = (section + number) * unit
            total += section
            section = 0
        else:
            if number == 0:
                number = 1
            section += number * unit
        number = 0
    return float(total + section + number)


def _parse_number_value(text: str) -> float | None:
    cleaned = (
        text.replace(",", "")
        .replace("，", "")
        .replace("￥", "")
        .replace("¥", "")
    )
    unit_match = re.search(r"(\d+(?:\.\d+)?)\s*(千|万)", cleaned)
    if unit_match:
        multiplier = 1000 if unit_match.group(2) == "千" else 10000
        value = float(unit_match.group(1)) * multiplier
        return value if value > 0 else None

    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if match:
        value = float(match.group(0))
        return value if value > 0 else None

    chinese_match = re.search(rf"[{_CN_NUMBER_CHARS}]+", cleaned)
    if chinese_match:
        value = _parse_chinese_number(chinese_match.group(0))
        return value if value is not None and value > 0 else None
    return None


def _parse_standalone_number_value(text: str) -> float | None:
    cleaned = text.strip()
    cleaned = re.sub(r"^(大概|大约|约|差不多|是|有|为|还|欠)\s*", "", cleaned)
    cleaned = re.sub(r"\s*(左右|上下|元|块|人民币|整)$", "", cleaned)
    cleaned = cleaned.replace("，", "").replace(",", "").strip()
    if not cleaned:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:千|万)?", cleaned):
        return _parse_number_value(cleaned)
    if re.fullmatch(rf"[{_CN_NUMBER_CHARS}]+", cleaned):
        return _parse_number_value(cleaned)
    return None


def _parse_period_value(text: str) -> int | None:
    cleaned = text.strip()
    if "半年" in cleaned:
        return 6
    if "一年半" in cleaned:
        return 18
    if "两年" in cleaned:
        return 24

    year_match = re.search(rf"([{_CN_NUMBER_CHARS}0-9]+)\s*年", cleaned)
    if year_match:
        years = _parse_number_value(year_match.group(1))
        if years is not None:
            return int(round(years * 12))

    month_match = re.search(
        rf"([{_CN_NUMBER_CHARS}0-9]+)\s*(?:个月|月|期)",
        cleaned,
    )
    if month_match:
        months = _parse_number_value(month_match.group(1))
        if months is not None:
            return int(round(months))

    if re.fullmatch(r"\s*\d+\s*", cleaned):
        return int(cleaned.strip())
    return None


def _parse_apr_value(text: str) -> float | None:
    cleaned = text.strip()
    if "百分之" in cleaned:
        tail = cleaned.split("百分之", 1)[1]
        value = _parse_number_value(tail)
        return round(value / 100, 8) if value is not None else None
    if "%" in cleaned or "％" in cleaned:
        value = _parse_number_value(cleaned)
        return round(value / 100, 8) if value is not None else None
    value = _parse_number_value(cleaned)
    if value is None:
        return None
    if value <= 1:
        return value
    if value <= 100:
        return round(value / 100, 8)
    return None


def _parse_labeled_apr(text: str) -> float | None:
    match = re.search(
        rf"(?:利率|年化)[^0-9{_CN_NUMBER_CHARS}]{{0,8}}"
        rf"([0-9]+(?:\.[0-9]+)?\s*[%％]?|[{_CN_NUMBER_CHARS}]+)",
        text,
    )
    if not match:
        return None
    return _parse_apr_value(match.group(1))

def _parse_remaining_ratio(text: str) -> float | None:
    cleaned = text.strip()
    if "一半" in cleaned or re.search(r"剩\s*半", cleaned):
        return 0.5
    if any(term in cleaned for term in ("还剩", "未还", "剩余比例", "欠款比例")):
        if "百分之" in cleaned or "%" in cleaned or "％" in cleaned:
            return _parse_apr_value(cleaned)
    return None


def _extract_original_amount(text: str) -> float | None:
    match = re.search(
        rf"(?:买(?:的时候)?|总价|原价|价格|花了|一共)[^0-9{_CN_NUMBER_CHARS}]{{0,6}}"
        rf"([0-9][0-9,]*(?:\.[0-9]+)?|[{_CN_NUMBER_CHARS}]+)",
        text,
    )
    if not match:
        return None
    return _parse_number_value(match.group(1))


def _extract_labeled_money(text: str, labels: tuple[str, ...]) -> float | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})[^0-9{_CN_NUMBER_CHARS}]{{0,8}}"
        rf"([0-9][0-9,]*(?:\.[0-9]+)?|[{_CN_NUMBER_CHARS}]+)",
        text,
    )
    if not match:
        return None
    return _parse_number_value(match.group(1))


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
        max_clarification_turns: int | None = None,
    ) -> None:
        self._draft_store = draft_store
        self._session_store = session_store
        self._agent_runner = agent_runner
        self._llm_client = llm_client
        self._conversation_store = conversation_store
        maximum = (
            max_clarification_turns
            if max_clarification_turns is not None
            else int(os.getenv("MAX_CLARIFICATION_TURNS", "8"))
        )
        if not 1 <= maximum <= 50:
            raise ValueError("max_clarification_turns must be between 1 and 50")
        self._max_clarification_turns = maximum

    def submit(
        self,
        payload: NaturalLanguageIntakeRequest,
        *,
        previous_question: str | None = None,
    ) -> IntakeResponse:
        """Extract one turn and return a question, an invalid result, or a preview."""

        existing: DraftState | None = None
        if payload.conversation_id is not None:
            existing = self._draft_store.get(payload.conversation_id)

        conversation_id = (
            existing.conversation_id if existing is not None else self._new_conversation_id()
        )
        used_turns = existing.clarification_turns if existing is not None else 0

        # The first user message is free. Once the user has used all follow-up
        # turns, return a deterministic exit path without another model call and
        # without modifying the structured draft.
        if existing is not None and used_turns >= self._max_clarification_turns:
            return IntakeResponse(
                conversation_id=conversation_id,
                status="clarification_limit",
                reply=(
                    "我已经记录了你目前提供的信息。为了避免反复追问，"
                    "你可以改用结构化表单继续补充，或者点击重新开始。"
                ),
                missing_fields=existing.missing_fields,
                clarification_turns=used_turns,
                max_clarification_turns=self._max_clarification_turns,
                remaining_clarification_turns=0,
                preview=self._preview(existing.draft),
                warnings=["MAX_CLARIFICATION_TURNS_REACHED"],
            )

        deterministic_draft = (
            self._apply_pending_answer(existing, payload.message)
            if existing is not None
            else None
        )
        if deterministic_draft is not None:
            extraction = ExtractionResult(
                status="needs_more_info",
                draft=deterministic_draft,
                warnings=["DETERMINISTIC_FIELD_FILLED"],
            )
        else:
            try:
                extraction = self._extract(
                    user_message=payload.message,
                    existing_draft=existing.draft if existing is not None else None,
                    previous_question=previous_question
                    or (existing.pending_question if existing is not None else None),
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
                pending_question=existing.pending_question if existing is not None else None,
                turn=used_turns,
            )
            return IntakeResponse(
                conversation_id=state.conversation_id,
                status="invalid",
                reply="暂时无法可靠解析这段描述，请补充更明确的金额、期数和利率信息。",
                missing_fields=state.missing_fields,
                clarification_turns=used_turns,
                max_clarification_turns=self._max_clarification_turns,
                remaining_clarification_turns=max(
                    0, self._max_clarification_turns - used_turns
                ),
                warnings=extraction.warnings or ["EXTRACTION_INVALID"],
            )

        if extraction.draft is None:
            state = self._save_state(
                existing=existing,
                conversation_id=conversation_id,
                draft=existing.draft if existing is not None else AssessmentDraft(),
                missing_fields=existing.missing_fields if existing is not None else [],
                pending_question=existing.pending_question if existing is not None else None,
                turn=used_turns,
            )
            return IntakeResponse(
                conversation_id=state.conversation_id,
                status="invalid",
                reply="没有提取到可用于评估的结构化信息，请重新描述。",
                missing_fields=state.missing_fields,
                clarification_turns=used_turns,
                max_clarification_turns=self._max_clarification_turns,
                remaining_clarification_turns=max(
                    0, self._max_clarification_turns - used_turns
                ),
                warnings=["EXTRACTION_EMPTY"],
            )

        merged_draft = self._merge_drafts(
            existing.draft if existing is not None else AssessmentDraft(),
            extraction.draft,
        )
        merged_draft = self._apply_debt_kind_signal(merged_draft, payload.message)
        merged_draft = self._apply_message_signals(merged_draft, payload.message)
        merged_draft = self._mark_unknown_apr(
            self._normalize_draft(merged_draft),
            payload.message,
            target_debt_index=(
                existing.current_debt_index if existing is not None else None
            ),
        )
        missing_fields = self._collect_missing_fields(merged_draft)
        draft_changed = (
            existing is not None
            and merged_draft.model_dump(mode="json")
            != existing.draft.model_dump(mode="json")
        )
        no_progress_turns = (
            existing.no_progress_turns + 1
            if existing is not None and not draft_changed
            else 0
        )
        response_warnings = list(extraction.warnings)
        if any(
            "remaining_principal" in debt.derived_fields
            and debt.original_amount is not None
            and debt.remaining_ratio is not None
            for debt in (merged_draft.debts or [])
        ):
            if "REMAINING_PRINCIPAL_ESTIMATED" not in response_warnings:
                response_warnings.append("REMAINING_PRINCIPAL_ESTIMATED")

        if self._has_invalid_total_income(merged_draft):
            state = self._save_state(
                existing=existing,
                conversation_id=conversation_id,
                draft=merged_draft,
                missing_fields=["income.positive_total"],
                pending_question="请确认你的生活费或兼职收入，当前总收入不能为零。",
                turn=used_turns,
            )
            return IntakeResponse(
                conversation_id=state.conversation_id,
                status="invalid",
                reply="当前收入信息不合法：生活费与兼职收入合计必须大于零。",
                missing_fields=state.missing_fields,
                clarification_turns=used_turns,
                max_clarification_turns=self._max_clarification_turns,
                remaining_clarification_turns=max(
                    0, self._max_clarification_turns - used_turns
                ),
                warnings=["INVALID_TOTAL_INCOME"],
            )

        if missing_fields:
            question = self._build_question(missing_fields, merged_draft)
            if existing is not None and not draft_changed:
                question = self._build_no_progress_question(
                    missing_fields,
                    merged_draft,
                    no_progress_turns,
                )
                if "NO_PROGRESS_DETECTED" not in response_warnings:
                    response_warnings.append("NO_PROGRESS_DETECTED")
            context_index, context_label = self._question_context(
                missing_fields[0],
                merged_draft,
            )
            # Only a follow-up turn that still asks for more information consumes
            # one clarification round. The initial message never consumes one.
            next_turns = used_turns + 1 if existing is not None else 0
            state = self._save_state(
                existing=existing,
                conversation_id=conversation_id,
                draft=merged_draft,
                missing_fields=missing_fields,
                pending_question=question,
                turn=next_turns,
                pending_field=missing_fields[0],
                no_progress_turns=no_progress_turns,
                current_debt_index=context_index,
                current_debt_label=context_label,
            )
            return IntakeResponse(
                conversation_id=state.conversation_id,
                status="needs_more_info",
                reply=question,
                missing_fields=missing_fields,
                clarification_turns=next_turns,
                max_clarification_turns=self._max_clarification_turns,
                remaining_clarification_turns=max(
                    0, self._max_clarification_turns - next_turns
                ),
                preview=self._preview(merged_draft),
                warnings=response_warnings,
            )

        state = self._save_state(
            existing=existing,
            conversation_id=conversation_id,
            draft=merged_draft,
            missing_fields=[],
            pending_question=None,
            turn=used_turns,
            pending_field=None,
            no_progress_turns=0,
        )
        return IntakeResponse(
            conversation_id=state.conversation_id,
            status="ready_for_confirmation",
            reply="信息已整理完成，请确认以下内容后开始风险评估。",
            missing_fields=[],
            clarification_turns=used_turns,
            max_clarification_turns=self._max_clarification_turns,
            remaining_clarification_turns=max(
                0, self._max_clarification_turns - used_turns
            ),
            preview=self._preview(merged_draft),
            warnings=response_warnings,
        )

    def confirm(
        self,
        conversation_id: str,
        assessment_request: AssessmentRequest | None = None,
    ) -> AgentResponse:
        """Confirm the draft, create a session and run the existing M4 chain."""

        try:
            state = self._draft_store.get(conversation_id)
        except (DraftNotFound, DraftExpired) as exc:
            # Confirmation is intentionally idempotent. A browser double click
            # or a Streamlit rerun must not surface a misleading DraftNotFound
            # after the first confirmation already created a session.
            if self._conversation_store is not None:
                conversation = self._conversation_store.get_optional(conversation_id)
                if conversation is not None and conversation.session_id is not None:
                    response = self._agent_runner.assess(conversation.session_id)
                    return response.model_copy(update={"session_id": conversation.session_id})
            raise IntakeNotReady("draft has already been confirmed or expired") from exc
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
        return response.model_copy(update={"session_id": request.session_id})

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
                clear_active_task=True,
                clear_active_scenario=True,
            )
        except (ConversationNotFound, ConversationExpired):
            self._conversation_store.create(
                conversation_id=conversation_id,
                session_id=session_id,
                current_intent="risk_explanation",
                active_task=None,
            )
            self._conversation_store.update(
                conversation_id,
                last_assessment_id=assessment_id,
                last_tool="run_risk_assessment",
                last_answer_type="assessment",
                clear_active_task=True,
                clear_active_scenario=True,
            )

    @classmethod
    def _apply_pending_answer(
        cls,
        existing: DraftState,
        user_message: str,
    ) -> AssessmentDraft | None:
        field = existing.pending_field or (
            existing.missing_fields[0] if existing.missing_fields else None
        )
        if field is None:
            return None

        message = user_message.strip()
        normalized = message.lower()
        draft = existing.draft

        debt_match = re.match(r"debts\[(\d+)\]\.(\w+)", field)
        if debt_match:
            if any(term in normalized for term in ("生活费", "兼职", "工资", "收入", "奖学金")):
                return None
            index = int(debt_match.group(1))
            field_name = debt_match.group(2)
            debts = list(draft.debts or [])
            if index >= len(debts):
                return None
            debt = debts[index]
            updates: dict[str, Any] = {}

            monthly = _extract_labeled_money(
                normalized,
                ("每月还", "每个月还", "每月", "每个月", "月供"),
            )
            if monthly is not None:
                updates["monthly_payment"] = monthly

            total = _extract_labeled_money(
                normalized,
                ("总共还要还", "总共还", "总还款", "一共还"),
            )
            if total is not None:
                updates["total_remaining_repayment"] = total

            principal = _extract_labeled_money(
                normalized,
                ("剩余本金", "本金", "现在还欠", "还欠", "欠了"),
            )
            if principal is not None:
                updates["remaining_principal"] = principal

            explicit_period_answer = bool(
                re.search(
                    rf"(还剩|还要还|剩余).{{0,8}}"
                    rf"([{_CN_NUMBER_CHARS}0-9]+\s*(期|个月|月|年)|半年|一年半)",
                    normalized,
                )
            ) or (field_name == "remaining_periods")
            if explicit_period_answer:
                periods = _parse_period_value(normalized)
                if periods is not None and periods >= 1:
                    updates["remaining_periods"] = periods

            if "利率" in normalized or "年化" in normalized:
                if any(term in normalized for term in _UNKNOWN_TERMS):
                    updates["nominal_apr"] = None
                    updates["nominal_apr_status"] = "unknown"
                else:
                    apr = _parse_labeled_apr(normalized) or (
                        _parse_apr_value(normalized)
                        if re.fullmatch(r"\s*[0-9.]+%?\s*", normalized)
                        else None
                    )
                    if apr is not None:
                        updates["nominal_apr"] = apr
                        updates["nominal_apr_status"] = "provided"

            if field_name == "kind":
                if any(term in normalized for term in ("自动续费", "订阅", "连续包月", "月费")):
                    updates["kind"] = "subscription"
                elif any(term in normalized for term in ("一次性", "普通分期", "分期")):
                    updates["kind"] = "installment"

            if field_name == "label" and message and len(message) <= 30:
                updates["label"] = message

            if not updates:
                if field_name == "remaining_periods":
                    periods = _parse_period_value(normalized)
                    if periods is not None and periods >= 1:
                        updates["remaining_periods"] = periods
                elif field_name == "nominal_apr":
                    if any(term in normalized for term in _UNKNOWN_TERMS):
                        updates["nominal_apr"] = None
                        updates["nominal_apr_status"] = "unknown"
                    else:
                        apr = _parse_labeled_apr(normalized) or (
                            _parse_apr_value(normalized)
                            if re.fullmatch(r"\s*[0-9.]+%?\s*", normalized)
                            else None
                        )
                        if apr is not None:
                            updates["nominal_apr"] = apr
                            updates["nominal_apr_status"] = "provided"
                elif field_name in {
                    "remaining_principal",
                    "total_remaining_repayment",
                    "final_payment",
                    "monthly_payment",
                }:
                    if not any(term in normalized for term in ("利率", "期", "月", "年")):
                        amount = _parse_standalone_number_value(normalized)
                        if amount is not None:
                            updates[field_name] = amount
                elif field_name == "monthly_cost":
                    amount = _parse_standalone_number_value(normalized)
                    if amount is not None:
                        updates["monthly_cost"] = amount

            if not updates:
                return None
            debts[index] = debt.model_copy(update=updates)
            return draft.model_copy(update={"debts": debts})

        subscription_match = re.match(
            r"recurring_subscriptions\[(\d+)\]\.(\w+)",
            field,
        )
        if subscription_match:
            index = int(subscription_match.group(1))
            field_name = subscription_match.group(2)
            subscriptions = list(draft.recurring_subscriptions or [])
            if index >= len(subscriptions):
                return None
            item = subscriptions[index]
            updates: dict[str, Any] = {}
            if field_name == "label" and message and len(message) <= 50:
                updates["label"] = message
            elif field_name == "monthly_cost":
                amount = _parse_standalone_number_value(normalized)
                if amount is not None:
                    updates["monthly_cost"] = amount
            if not updates:
                return None
            subscriptions[index] = item.model_copy(update=updates)
            return draft.model_copy(update={"recurring_subscriptions": subscriptions})

        if field == "debts":
            if any(term in normalized for term in ("没有", "没有负债", "没有分期", "还完", "结清")):
                return draft.model_copy(update={"debts": [], "no_debts": True})
            return None

        if field in {
            "income.monthly_disposable_allowance",
            "income.monthly_part_time_income",
        }:
            if any(
                term in normalized
                for term in ("本金", "月供", "分期", "还剩", "总还", "利率", "期数", "会员", "订阅")
            ):
                return None
            income = draft.income or IncomeDraft()
            if field.endswith("monthly_part_time_income") and any(
                term in normalized for term in _NO_VALUE_TERMS
            ):
                value = 0.0
            else:
                value = _parse_standalone_number_value(normalized)
            if value is None:
                return None
            updates = {field.rsplit(".", 1)[-1]: value}
            return draft.model_copy(
                update={"income": income.model_copy(update=updates)}
            )

        return None

    @classmethod
    def _apply_message_signals(
        cls,
        draft: AssessmentDraft,
        user_message: str,
    ) -> AssessmentDraft:
        debts = list(draft.debts or [])
        active_indices = [
            index
            for index, debt in enumerate(debts)
            if debt.settled is not True and debt.remaining_periods != 0
        ]
        if len(active_indices) != 1:
            return draft

        index = active_indices[0]
        debt = debts[index]
        if debt.kind == "subscription":
            return draft

        message = user_message.strip()
        updates: dict[str, Any] = {}
        original_amount = _extract_original_amount(message)
        remaining_ratio = _parse_remaining_ratio(message)
        derived_fields = list(debt.derived_fields)

        if original_amount is not None:
            updates["original_amount"] = original_amount
        if remaining_ratio is not None:
            updates["remaining_ratio"] = remaining_ratio

        effective_original = original_amount or debt.original_amount
        effective_ratio = remaining_ratio or debt.remaining_ratio
        if effective_original is not None and effective_ratio is not None:
            estimated = round(effective_original * effective_ratio, 2)
            if (
                debt.remaining_principal is None
                or abs(debt.remaining_principal - effective_original) < 1e-9
            ):
                updates["remaining_principal"] = estimated
                if "remaining_principal" not in derived_fields:
                    derived_fields.append("remaining_principal")

        principal = _extract_labeled_money(
            message,
            ("剩余本金", "本金", "现在还欠", "还欠", "欠了"),
        )
        if principal is not None:
            updates["remaining_principal"] = principal
            if "remaining_principal" in derived_fields:
                derived_fields.remove("remaining_principal")

        total = _extract_labeled_money(
            message,
            ("总共还要还", "总共还", "总还款", "一共还"),
        )
        if total is not None:
            updates["total_remaining_repayment"] = total

        monthly = _extract_labeled_money(
            message,
            ("每月还款", "每个月还款", "每月还", "每个月还", "月供"),
        )
        if monthly is not None:
            updates["monthly_payment"] = monthly

        if any(term in message for term in ("还剩", "还要还", "剩余", "一年", "半年")):
            periods = _parse_period_value(message)
            if periods is not None and periods >= 1:
                updates["remaining_periods"] = periods

        if not updates:
            return draft
        updates["derived_fields"] = derived_fields
        debts[index] = debt.model_copy(update=updates)
        return draft.model_copy(update={"debts": debts})
    def _extract(
        self,
        *,
        user_message: str,
        existing_draft: AssessmentDraft | None,
        previous_question: str | None = None,
    ) -> ExtractionResult:
        response = self._llm_client.complete(
            messages=build_extraction_messages(
                user_message=user_message,
                existing_draft=existing_draft,
                previous_question=previous_question,
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
        pending_field: str | None = None,
        no_progress_turns: int | None = None,
        current_debt_index: int | None = None,
        current_debt_label: str | None = None,
    ) -> DraftState:
        resolved_pending_field = (
            pending_field
            or (missing_fields[0] if missing_fields else None)
        )
        resolved_index = current_debt_index
        resolved_label = current_debt_label
        if resolved_pending_field is not None and resolved_index is None:
            resolved_index, resolved_label = self._question_context(
                resolved_pending_field,
                draft,
            )
        resolved_progress = (
            no_progress_turns
            if no_progress_turns is not None
            else (existing.no_progress_turns if existing is not None else 0)
        )

        if existing is None:
            return self._draft_store.create(
                conversation_id=conversation_id,
                draft=draft,
                missing_fields=missing_fields,
                pending_question=pending_question,
                pending_field=resolved_pending_field,
                no_progress_turns=resolved_progress,
                current_debt_index=resolved_index,
                current_debt_label=resolved_label,
                clarification_turns=turn,
            )
        updated = existing.model_copy(
            update={
                "draft": draft,
                "missing_fields": missing_fields,
                "pending_question": pending_question,
                "pending_field": resolved_pending_field,
                "no_progress_turns": resolved_progress,
                "clarification_turns": turn,
                "current_debt_index": resolved_index,
                "current_debt_label": resolved_label,
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
    def _is_ambiguous_subscription_label(debt: DebtDraft) -> bool:
        if debt.label is None:
            return False
        label = debt.label
        has_subscription_word = any(
            term in label for term in ("会员", "订阅", "自动续费", "连续包月", "包月", "月费")
        )
        return has_subscription_word and "分期" in label

    @classmethod
    def _apply_debt_kind_signal(
        cls,
        draft: AssessmentDraft,
        user_message: str,
    ) -> AssessmentDraft:
        normalized = user_message.lower()
        if any(term in normalized for term in ("自动续费", "订阅", "每月扣", "连续包月", "月费")):
            kind = "subscription"
        elif any(term in normalized for term in ("一次性", "不是订阅", "普通分期")):
            kind = "installment"
        else:
            return draft
        debts = [
            debt.model_copy(update={"kind": kind})
            if cls._is_ambiguous_subscription_label(debt) or debt.kind == "unknown"
            else debt
            for debt in (draft.debts or [])
        ]
        return draft.model_copy(update={"debts": debts})

    @staticmethod
    def _subscription_like(debt: DebtDraft) -> bool:
        if debt.label is None:
            return False
        if debt.kind == "installment":
            return False
        label = debt.label
        terms = ("会员", "订阅", "自动续费", "连续包月", "包月", "月费")
        has_subscription_label = any(term in label for term in terms)
        # Recurring services do not have a principal. A label containing
        # "分期" is ambiguous and must be clarified, not silently moved.
        has_no_principal = debt.remaining_principal is None
        if debt.kind == "subscription":
            return has_subscription_label and has_no_principal
        return (
            has_subscription_label
            and has_no_principal
            and "分期" not in label
        )

    @classmethod
    def _normalize_draft(cls, draft: AssessmentDraft) -> AssessmentDraft:
        debts: list[DebtDraft] | None = None
        subscriptions = list(draft.recurring_subscriptions or [])
        if draft.debts is not None:
            debts = []
            for debt in draft.debts:
                if cls._subscription_like(debt):
                    subscriptions = cls._merge_subscriptions(
                        subscriptions,
                        [
                            RecurringSubscriptionDraft(
                                label=debt.label or "会员订阅",
                                monthly_cost=debt.monthly_payment,
                            )
                        ],
                    ) or []
                    continue
                if cls._is_ambiguous_subscription_label(debt) and debt.kind is None:
                    debt = debt.model_copy(update={"kind": "unknown"})
                debt = cls._derive_debt_fields(debt)
                settled = debt.settled is True or debt.remaining_periods == 0
                apr_status = debt.nominal_apr_status
                if debt.nominal_apr is not None:
                    apr_status = "provided"
                elif apr_status is None:
                    apr_status = "not_mentioned"
                debts.append(
                    debt.model_copy(
                        update={
                            "settled": settled,
                            "nominal_apr_status": apr_status,
                        }
                    )
                )
        return draft.model_copy(
            update={
                "debts": debts,
                "recurring_subscriptions": subscriptions if subscriptions else draft.recurring_subscriptions,
            }
        )

    @classmethod
    def _derive_debt_fields(cls, debt: DebtDraft) -> DebtDraft:
        derivations = list(debt.derived_fields)
        principal = debt.remaining_principal
        total = debt.total_remaining_repayment
        monthly = debt.monthly_payment
        periods = debt.remaining_periods
        final_payment = debt.final_payment
        original_amount = debt.original_amount
        remaining_ratio = debt.remaining_ratio
        if (
            principal is None
            and original_amount is not None
            and remaining_ratio is not None
        ):
            principal = round(original_amount * remaining_ratio, 2)
            if "remaining_principal" not in derivations:
                derivations.append("remaining_principal")
        if periods is None and total is not None and monthly is not None:
            ratio = total / monthly
            rounded = round(ratio)
            if abs(ratio - rounded) < 1e-9 and rounded >= 1:
                periods = int(rounded)
                if "remaining_periods" not in derivations:
                    derivations.append("remaining_periods")
            elif final_payment is not None and total > monthly:
                full_payments = int(total // monthly)
                remainder = round(total - full_payments * monthly, 6)
                if abs(remainder - final_payment) < 1e-9:
                    periods = full_payments + 1
                    if "remaining_periods" not in derivations:
                        derivations.append("remaining_periods")
        return debt.model_copy(
            update={
                "remaining_principal": principal,
                "remaining_periods": periods,
                "derived_fields": derivations,
            }
        )

    @classmethod
    def _active_debts(cls, draft: AssessmentDraft) -> list[DebtDraft]:
        return [
            debt
            for debt in (draft.debts or [])
            if debt.settled is not True and debt.remaining_periods != 0
        ]

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
            if new_debt.id:
                target_index = next(
                    (i for i, old_debt in enumerate(merged) if old_debt.id == new_debt.id),
                    None,
                )
            if target_index is None and new_debt.label:
                target_index = next(
                    (
                        i
                        for i, old_debt in enumerate(merged)
                        if old_debt.label == new_debt.label
                    ),
                    None,
                )
            # A label-less correction can refer to the debt at the same
            # position. A newly named debt must be appended instead of
            # overwriting an unrelated existing debt.
            if target_index is None and new_debt.label is None and index < len(merged):
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
            if target_index is None and new_item.label is None and index < len(merged):
                target_index = index
            if target_index is None:
                merged.append(new_item)
            else:
                data = merged[target_index].model_dump(mode="json")
                data.update(new_item.model_dump(mode="json", exclude_none=True))
                merged[target_index] = RecurringSubscriptionDraft.model_validate(data)
        return merged

    @classmethod
    def _collect_missing_fields(cls, draft: AssessmentDraft) -> list[str]:
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
            if draft.debts is None or (not draft.debts and draft.no_debts is not True):
                missing.append("debts")
            else:
                for index, debt in enumerate(draft.debts):
                    if debt.settled is True or debt.remaining_periods == 0:
                        continue
                    if debt.kind == "unknown":
                        missing.append(f"debts[{index}].kind")
                    if debt.remaining_principal is None:
                        missing.append(f"debts[{index}].remaining_principal")
                    if debt.monthly_payment is None:
                        missing.append(f"debts[{index}].monthly_payment")
                    if debt.remaining_periods is None:
                        total = debt.total_remaining_repayment
                        monthly = debt.monthly_payment
                        if (
                            total is not None
                            and monthly is not None
                            and debt.final_payment is None
                            and abs((total / monthly) - round(total / monthly)) > 1e-9
                        ):
                            missing.append(f"debts[{index}].final_payment")
                        else:
                            missing.append(f"debts[{index}].remaining_periods")
                    if (
                        debt.nominal_apr is None
                        and debt.nominal_apr_status != "unknown"
                    ):
                        missing.append(f"debts[{index}].nominal_apr")

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
    def _question_context(
        field: str,
        draft: AssessmentDraft,
    ) -> tuple[int | None, str | None]:
        match = re.match(r"debts\[(\d+)\]", field)
        if match:
            debts = draft.debts or []
            index = int(match.group(1))
            if 0 <= index < len(debts):
                debt = debts[index]
                if debt.settled is True or debt.remaining_periods == 0:
                    return None, None
                label = debt.label or f"第{index + 1}笔分期"
                return index, label
        match = re.match(r"recurring_subscriptions\[(\d+)\]", field)
        if match:
            index = int(match.group(1))
            subscriptions = draft.recurring_subscriptions or []
            if 0 <= index < len(subscriptions):
                return None, subscriptions[index].label or f"第{index + 1}个订阅"
        return None, None

    @staticmethod
    def _build_question(missing_fields: list[str], draft: AssessmentDraft) -> str:
        field = missing_fields[0]
        tail = field.rsplit(".", 1)[-1]
        context_index, context_label = IntakeService._question_context(field, draft)
        if context_index is not None and context_label:
            subject = f"{context_label}这笔分期"
        elif context_label:
            subject = context_label
        else:
            subject = "这笔账单"
        if field.startswith("income.monthly_disposable_allowance"):
            question = "你每个月大概有多少生活费？"
        elif field.startswith("income.monthly_part_time_income"):
            question = "你每个月大概有多少兼职收入？没有的话可以直接说没有。"
        elif field == "debts":
            question = "你现在还有正在还款的分期吗？如果已经还完，可以直接说已经还完。"
        elif tail == "remaining_principal":
            question = f"{subject}现在还欠多少钱？这里填剩余欠款，不是每个月要还的钱。"
        elif tail == "total_remaining_repayment":
            question = f"{subject}总共还要还多少钱？"
        elif tail == "final_payment":
            question = f"{subject}最后一期大概还要还多少？"
        elif tail == "monthly_payment":
            question = f"{subject}每个月大概还多少？"
        elif tail == "remaining_periods":
            question = f"{subject}大概还要还多少期或几个月？"
        elif tail == "nominal_apr":
            question = f"{subject}当时约定的利率大概是多少？不清楚也可以直接说不知道。"
        elif tail == "kind":
            question = f"{subject}是一次性分期，还是每月自动续费？"
        elif tail == "label":
            question = f"{subject}叫什么名字？"
        elif tail == "monthly_cost":
            question = f"{subject}每个月大概扣多少钱？"
        elif field == "income.positive_total":
            question = "请确认一下你每个月的生活费和兼职收入大概是多少。"
        else:
            question = "请再补充一下这笔账单的还款情况。"
        return "还差一点信息：" + question

    @staticmethod
    def _build_no_progress_question(
        missing_fields: list[str],
        draft: AssessmentDraft,
        no_progress_turns: int,
    ) -> str:
        field = missing_fields[0]
        tail = field.rsplit(".", 1)[-1]
        context_index, context_label = IntakeService._question_context(field, draft)
        if context_index is not None and context_label:
            subject = f"{context_label}这笔分期"
        elif context_label:
            subject = context_label
        else:
            subject = "这笔账单"

        if tail == "remaining_principal":
            question = (
                "我收到了你的补充，但还没能确定金额。"
                f"{subject}现在是还剩多少欠款？可以直接输入“还欠3000元”。"
            )
        elif tail == "total_remaining_repayment":
            question = (
                "我收到了你的补充，但还没分清金额含义。"
                f"{subject}总共还要还多少钱？不是现在剩余欠款。"
            )
        elif tail == "monthly_payment":
            question = f"我还需要确认一下，{subject}每个月实际要还多少？"
        elif tail == "remaining_periods":
            question = f"我还需要确认一下，{subject}还要还多少期或几个月？"
        elif tail == "nominal_apr":
            question = (
                f"{subject}的利率还不清楚。你可以填类似“12%”，"
                "或者直接说“不知道”。"
            )
        else:
            question = "这轮补充还没有写入草稿，请换一种更明确的说法。"

        if no_progress_turns >= 2:
            question += " 也可以改用结构化表单继续，已经填过的信息不会丢失。"
        return "还差一点信息：" + question

    @staticmethod
    def _mark_unknown_apr(
        draft: AssessmentDraft,
        user_message: str,
        *,
        target_debt_index: int | None = None,
    ) -> AssessmentDraft:
        normalized = user_message.lower()
        mentions_apr = "利率" in normalized or "年化" in normalized
        if not (
            mentions_apr
            and any(term in normalized for term in _UNKNOWN_TERMS)
        ):
            return draft

        debts = list(draft.debts or [])
        if target_debt_index is not None:
            if 0 <= target_debt_index < len(debts) and debts[target_debt_index].nominal_apr is None:
                debts[target_debt_index] = debts[target_debt_index].model_copy(
                    update={
                        "nominal_apr": None,
                        "nominal_apr_status": "unknown",
                    }
                )
        elif len(debts) == 1 and debts[0].nominal_apr is None:
            debts[0] = debts[0].model_copy(
                update={
                    "nominal_apr": None,
                    "nominal_apr_status": "unknown",
                }
            )
        return draft.model_copy(update={"debts": debts})

    @staticmethod
    def _preview(draft: AssessmentDraft) -> dict[str, Any]:
        preview = draft.model_dump(mode="json", exclude_none=True)
        # Internal markers are not part of the user-facing preview.
        preview.pop("no_debts", None)
        for debt in preview.get("debts", []):
            debt.pop("nominal_apr_status", None)
            debt.pop("kind", None)
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
            for index, debt in enumerate(IntakeService._active_debts(draft)):
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
