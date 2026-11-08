"""M4-B unified chat orchestration."""

from __future__ import annotations

import time
from uuid import uuid4

from riskguard.agent.deepseek import ChatModel
from riskguard.agent.intake import IntakeNotReady, IntakeService
from riskguard.agent.intents import classify_intent
from riskguard.agent.runner import AgentRunner
from riskguard.agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    EducationAnswer,
    IntakeResponse,
    NaturalLanguageIntakeRequest,
    ScenarioSimulationResult,
)
from riskguard.models import AgentError, ToolActivity
from riskguard.services import (
    ChatMemoryStore,
    ConversationExpired,
    ConversationNotFound,
    ConversationStore,
    DraftExpired,
    DraftNotFound,
    DraftStore,
    ScenarioStore,
)
from riskguard.services.education_service import EducationService
from riskguard.services.scenario_service import ScenarioService
from riskguard.tools import (
    RETRIEVE_EDUCATION_TOPIC_TOOL_NAME,
    SIMULATE_NEW_INSTALLMENT_TOOL_NAME,
    ToolArgumentError,
    ToolExecutor,
    ToolNotFound,
)


class ChatOrchestrator:
    """Run bounded chat turns without allowing the LLM to choose arbitrary actions."""

    def __init__(
        self,
        *,
        conversation_store: ConversationStore,
        draft_store: DraftStore,
        scenario_store: ScenarioStore,
        intake_service: IntakeService,
        agent_runner: AgentRunner,
        tool_executor: ToolExecutor,
        education_service: EducationService,
        scenario_service: ScenarioService,
        llm_client: ChatModel,
        chat_memory_store: ChatMemoryStore | None = None,
    ) -> None:
        self._conversation_store = conversation_store
        self._draft_store = draft_store
        self._scenario_store = scenario_store
        self._intake_service = intake_service
        self._agent_runner = agent_runner
        self._tool_executor = tool_executor
        self._education_service = education_service
        self._scenario_service = scenario_service
        self._llm_client = llm_client
        self._memory_store = (
            chat_memory_store
            if chat_memory_store is not None
            else ChatMemoryStore()
        )

    def chat(self, request: AgentChatRequest) -> AgentChatResponse:
        response = self._chat_impl(request)
        conversation = self._conversation_store.get_optional(response.conversation_id)
        if conversation is None:
            return response
        self._memory_store.append(
            response.conversation_id,
            role="user",
            content=request.message,
        )
        self._memory_store.append(
            response.conversation_id,
            role="assistant",
            content=response.reply,
            intent=conversation.current_intent if conversation else None,
            topic=conversation.last_topic if conversation else None,
            assessment_id=(
                conversation.last_assessment_id if conversation else None
            ),
            answer_type=response.status,
            tool=conversation.last_tool if conversation else None,
        )
        return response

    def _chat_impl(self, request: AgentChatRequest) -> AgentChatResponse:
        conversation_id = request.conversation_id or self._new_conversation_id()
        conversation = self._conversation_store.get_optional(conversation_id)
        if request.conversation_id is not None and conversation is None:
            return self._error(
                conversation_id,
                "会话不存在或已过期，请重新开始。",
                "CONVERSATION_NOT_FOUND",
            )

        draft = self._get_draft(conversation_id)
        memory = self._memory_store.get_optional(conversation_id)
        previous_question = None
        if draft is not None:
            previous_question = (
                draft.pending_question
                or ChatMemoryStore.last_assistant_message(memory)
            )
        intent = classify_intent(
            request.message,
            has_draft=draft is not None,
            has_session=conversation is not None and conversation.session_id is not None,
        )

        if intent == "out_of_scope":
            self._remember(
                conversation_id,
                current_intent=intent,
                last_answer_type="out_of_scope",
            )
            return AgentChatResponse(
                conversation_id=conversation_id,
                status="out_of_scope",
                reply=(
                    "我不能推荐借贷平台，也不能判断贷款是否可以通过、授信额度或放款结果。"
                    "我可以帮助你理解负债压力、现金流和理性消费风险。"
                ),
            )

        if intent in {"clarification", "assessment_intake"}:
            # A brand-new chat has a generated UI conversation_id but no
            # DraftStore record yet. Let IntakeService allocate the first draft
            # id, and keep using the existing id only for clarification turns.
            intake_conversation_id = conversation_id if draft is not None else None
            intake = self._intake_service.submit(
                NaturalLanguageIntakeRequest(
                    conversation_id=intake_conversation_id,
                    message=request.message,
                ),
                previous_question=previous_question,
            )
            self._remember_intake(intake.conversation_id, intake)
            return self._from_intake(intake)

        if intent == "education":
            return self._handle_education(conversation_id, request.message)

        if intent == "risk_explanation":
            if conversation is None or conversation.session_id is None:
                return self._ask_for_assessment(conversation_id)
            return self._handle_risk_explanation(conversation_id, conversation.session_id)

        if intent == "scenario_simulation":
            if conversation is None or conversation.session_id is None:
                return self._ask_for_assessment(conversation_id)
            return self._handle_scenario(conversation_id, conversation.session_id, request.message)

        return self._error(
            conversation_id,
            "暂时无法确定这句话对应的操作，请换一种说法。",
            "INTENT_UNKNOWN",
        )

    def _handle_education(self, conversation_id: str, message: str) -> AgentChatResponse:
        card = self._education_service.find_topic(message)
        if card is None:
            self._remember(
                conversation_id,
                current_intent="out_of_scope",
                last_answer_type="out_of_scope",
            )
            return AgentChatResponse(
                conversation_id=conversation_id,
                status="out_of_scope",
                reply="我目前只能回答与分期、IRR、现金流、订阅、预算和理性消费相关的教育问题。",
            )

        started = time.perf_counter()
        try:
            retrieved = self._tool_executor.execute(
                RETRIEVE_EDUCATION_TOPIC_TOOL_NAME,
                {"topic_id": card.topic_id},
            )
            if not hasattr(retrieved, "topic_id"):
                raise ToolArgumentError("education tool returned an invalid card")
            answer: EducationAnswer = self._education_service.answer(
                question=message,
                topic_id=card.topic_id,
            )
        except (ToolArgumentError, ToolNotFound):
            return self._error(
                conversation_id,
                "科普内容暂时不可用，请稍后再试。",
                "EDUCATION_TOOL_FAILED",
            )

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        self._remember(
            conversation_id,
            current_intent="education",
            last_topic=card.topic_id,
            last_tool=RETRIEVE_EDUCATION_TOPIC_TOOL_NAME,
            last_answer_type="education",
        )
        return AgentChatResponse(
            conversation_id=conversation_id,
            status="education_answer",
            reply=answer.answer,
            education=answer,
            tool_activity=[
                ToolActivity(
                    tool=RETRIEVE_EDUCATION_TOPIC_TOOL_NAME,
                    status="succeeded",
                    latency_ms=latency_ms,
                )
            ],
            review_status=card.review_status,
        )

    def _handle_risk_explanation(
        self,
        conversation_id: str,
        session_id: str,
    ) -> AgentChatResponse:
        response = self._agent_runner.assess(session_id)
        self._remember(
            conversation_id,
            current_intent="risk_explanation",
            last_assessment_id=(
                response.assessment.assessment_id if response.assessment else None
            ),
            last_tool="run_risk_assessment",
            last_answer_type="risk_explanation",
        )
        if response.status == "error":
            return AgentChatResponse(
                conversation_id=conversation_id,
                status="error",
                reply="评估暂时不可用，请稍后重试。",
                error=response.error,
                tool_activity=response.tool_activity,
            )
        reply = (
            response.explanation.summary
            if response.explanation is not None
            else "已完成风险解释，请查看结构化评估结果。"
        )
        return AgentChatResponse(
            conversation_id=conversation_id,
            status="completed",
            reply=reply,
            assessment=response.assessment,
            explanation=response.explanation,
            tool_activity=response.tool_activity,
            error=response.error,
        )

    def _handle_scenario(
        self,
        conversation_id: str,
        session_id: str,
        message: str,
    ) -> AgentChatResponse:
        extraction, scenario_id = self._scenario_service.extract_and_stage(message)
        if extraction.status == "needs_more_info" or extraction.missing_fields:
            self._remember(
                conversation_id,
                current_intent="scenario_simulation",
                last_answer_type="needs_more_info",
                clarification_turns=1,
                pending_question=extraction.question,
            )
            return AgentChatResponse(
                conversation_id=conversation_id,
                status="needs_more_info",
                reply=extraction.question or "请补充新增分期的本金、月供、期数和利率。",
                missing_fields=extraction.missing_fields,
            )
        if extraction.status == "invalid" or scenario_id is None:
            return self._error(
                conversation_id,
                "无法可靠解析新增分期情景，请补充更明确的金额、期数和利率。",
                "SCENARIO_EXTRACTION_FAILED",
            )

        started = time.perf_counter()
        try:
            scenario = self._tool_executor.execute(
                SIMULATE_NEW_INSTALLMENT_TOOL_NAME,
                {"session_id": session_id, "scenario_id": scenario_id},
            )
        except (ToolArgumentError, ToolNotFound):
            return self._error(
                conversation_id,
                "情景模拟暂时不可用，请确认会话信息后重试。",
                "SCENARIO_TOOL_FAILED",
            )
        if not isinstance(scenario, ScenarioSimulationResult):
            return self._error(
                conversation_id,
                "情景模拟返回了无法识别的结果。",
                "SCENARIO_RESULT_INVALID",
            )

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        self._remember(
            conversation_id,
            current_intent="scenario_simulation",
            last_tool=SIMULATE_NEW_INSTALLMENT_TOOL_NAME,
            last_assessment_id=scenario.scenario_assessment.assessment_id,
            last_answer_type="scenario",
        )
        return AgentChatResponse(
            conversation_id=conversation_id,
            status="completed",
            reply="已完成新增分期情景模拟，请查看工具返回的前后对比。",
            scenario=scenario,
            tool_activity=[
                ToolActivity(
                    tool=SIMULATE_NEW_INSTALLMENT_TOOL_NAME,
                    status="succeeded",
                    latency_ms=latency_ms,
                )
            ],
        )

    def _from_intake(self, intake: IntakeResponse) -> AgentChatResponse:
        if intake.status == "invalid":
            return AgentChatResponse(
                conversation_id=intake.conversation_id,
                status="error",
                reply=intake.reply,
                missing_fields=intake.missing_fields,
                clarification_turns=intake.clarification_turns,
                max_clarification_turns=intake.max_clarification_turns,
                remaining_clarification_turns=intake.remaining_clarification_turns,
                error=AgentError(code="INTAKE_INVALID", message=intake.reply),
            )
        return AgentChatResponse(
            conversation_id=intake.conversation_id,
            status=intake.status,
            reply=intake.reply,
            missing_fields=intake.missing_fields,
            clarification_turns=intake.clarification_turns,
            max_clarification_turns=intake.max_clarification_turns,
            remaining_clarification_turns=intake.remaining_clarification_turns,
            preview=intake.preview,
        )

    def _ask_for_assessment(self, conversation_id: str) -> AgentChatResponse:
        self._remember(
            conversation_id,
            current_intent="assessment_intake",
            last_answer_type="needs_more_info",
        )
        return AgentChatResponse(
            conversation_id=conversation_id,
            status="needs_more_info",
            reply="请先提供生活费、兼职收入和分期情况，我才能分析你的个人风险。",
        )

    def _error(
        self,
        conversation_id: str,
        reply: str,
        code: str,
    ) -> AgentChatResponse:
        return AgentChatResponse(
            conversation_id=conversation_id,
            status="error",
            reply=reply,
            error=AgentError(code=code, message=reply),
        )

    def _remember_intake(
        self,
        conversation_id: str,
        intake: IntakeResponse,
    ) -> None:
        self._remember(
            conversation_id,
            current_intent=(
                "clarification"
                if intake.status in {"needs_more_info", "clarification_limit"}
                else "assessment_intake"
            ),
            last_answer_type=intake.status,
            clarification_turns=intake.clarification_turns,
            pending_question=intake.reply if intake.status == "needs_more_info" else None,
        )

    def _remember(
        self,
        conversation_id: str,
        *,
        current_intent: str,
        last_topic: str | None = None,
        last_assessment_id: str | None = None,
        last_tool: str | None = None,
        last_answer_type: str | None = None,
        clarification_turns: int | None = None,
        pending_question: str | None = None,
    ) -> None:
        try:
            self._conversation_store.get(conversation_id)
            self._conversation_store.update(
                conversation_id,
                current_intent=current_intent,
                last_topic=last_topic,
                last_assessment_id=last_assessment_id,
                last_tool=last_tool,
                last_answer_type=last_answer_type,
                clarification_turns=clarification_turns,
                pending_question=pending_question,
            )
        except (ConversationNotFound, ConversationExpired):
            self._conversation_store.create(
                conversation_id=conversation_id,
                current_intent=current_intent,
            )
            self._conversation_store.update(
                conversation_id,
                last_topic=last_topic,
                last_assessment_id=last_assessment_id,
                last_tool=last_tool,
                last_answer_type=last_answer_type,
                clarification_turns=clarification_turns,
                pending_question=pending_question,
            )

    def _get_draft(self, conversation_id: str):
        try:
            return self._draft_store.get(conversation_id)
        except (DraftNotFound, DraftExpired):
            return None

    @staticmethod
    def _new_conversation_id() -> str:
        return f"conv_{uuid4().hex[:12]}"
