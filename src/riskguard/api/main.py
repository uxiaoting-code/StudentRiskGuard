"""FastAPI adapter for StudentRiskGuard M3."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from riskguard import __version__
from riskguard.agent import AgentRunner, ChatModel, DeepSeekClient
from riskguard.agent.chat import ChatOrchestrator
from riskguard.agent.intake import IntakeNotReady, IntakeService
from riskguard.api.auth import create_auth_router
from riskguard.auth import AuthService, AuthServiceError
from riskguard.agent.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    ConfirmIntakeRequest,
    EducationCard,
    IntakeResponse,
    NaturalLanguageIntakeRequest,
)
from riskguard.models import (
    ApiErrorDetail,
    ApiErrorResponse,
    AssessmentRequest,
    AgentResponse,
    AssessmentResult,
    HealthResponse,
    RunAssessmentRequest,
    SessionCreateResponse,
    SessionMetadata,
)
from riskguard.services import (
    AssessmentService,
    ConversationExpired,
    ConversationNotFound,
    ConversationStore,
    DraftExpired,
    DraftNotFound,
    DraftStore,
    DraftTurnLimit,
    ScenarioStore,
    SessionAlreadyExists,
    SessionExpired,
    SessionNotFound,
    SessionStore,
)
from riskguard.services.education_service import EducationService
from riskguard.services.scenario_service import ScenarioService
from riskguard.tools import (
    RUN_RISK_ASSESSMENT_TOOL_NAME,
    TOOL_DEFINITIONS,
    ToolArgumentError,
    ToolExecutor,
    ToolNotFound,
)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", f"req_{uuid4().hex[:12]}")


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    body = ApiErrorResponse(
        request_id=_request_id(request),
        error=ApiErrorDetail(code=code, message=message),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def create_app(
    *,
    session_store: SessionStore | None = None,
    draft_store: DraftStore | None = None,
    conversation_store: ConversationStore | None = None,
    scenario_store: ScenarioStore | None = None,
    education_service: EducationService | None = None,
    auth_service: AuthService | None = None,
    llm_client: ChatModel | None = None,
) -> FastAPI:
    store = session_store if session_store is not None else SessionStore()
    assessment_service = AssessmentService(store)
    model_client = llm_client or DeepSeekClient.from_env()
    auth = auth_service or AuthService()
    drafts = draft_store if draft_store is not None else DraftStore()
    conversations = (
        conversation_store if conversation_store is not None else ConversationStore()
    )
    scenarios = scenario_store if scenario_store is not None else ScenarioStore()
    education = (
        education_service
        if education_service is not None
        else EducationService(llm_client=model_client)
    )
    scenario_service = ScenarioService(
        scenario_store=scenarios,
        session_store=store,
        assessment_service=assessment_service,
        llm_client=model_client,
    )
    tool_executor = ToolExecutor(
        assessment_service,
        education_service=education,
        scenario_service=scenario_service,
    )
    agent_runner = AgentRunner(
        session_store=store,
        tool_executor=tool_executor,
        llm_client=model_client,
    )
    intake_service = IntakeService(
        draft_store=drafts,
        session_store=store,
        agent_runner=agent_runner,
        llm_client=model_client,
        conversation_store=conversations,
    )
    chat_orchestrator = ChatOrchestrator(
        conversation_store=conversations,
        draft_store=drafts,
        scenario_store=scenarios,
        intake_service=intake_service,
        agent_runner=agent_runner,
        tool_executor=tool_executor,
        education_service=education,
        scenario_service=scenario_service,
        llm_client=model_client,
    )

    api = FastAPI(
        title="StudentRiskGuard API",
        version=__version__,
        description=(
            "大学生负债压力自检与理性消费科普 Agent。提供可选账号、匿名会话、"
            "确定性评估工具、受约束智能解读和 API；不提供授信或借贷功能。"
        ),
    )
    api.state.session_store = store
    api.state.assessment_service = assessment_service
    api.state.tool_executor = tool_executor
    api.state.agent_runner = agent_runner
    api.state.draft_store = drafts
    api.state.conversation_store = conversations
    api.state.scenario_store = scenarios
    api.state.education_service = education
    api.state.scenario_service = scenario_service
    api.state.intake_service = intake_service
    api.state.chat_orchestrator = chat_orchestrator
    api.state.auth_service = auth
    api.include_router(create_auth_router(auth))

    @api.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = f"req_{uuid4().hex[:12]}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @api.exception_handler(SessionNotFound)
    async def handle_session_not_found(request: Request, exc: SessionNotFound):
        return _error_response(
            request,
            status.HTTP_404_NOT_FOUND,
            "SESSION_NOT_FOUND",
            "匿名会话不存在或已经删除。",
        )

    @api.exception_handler(SessionExpired)
    async def handle_session_expired(request: Request, exc: SessionExpired):
        return _error_response(
            request,
            status.HTTP_410_GONE,
            "SESSION_EXPIRED",
            "匿名会话已过期，请重新开始自检。",
        )

    @api.exception_handler(SessionAlreadyExists)
    async def handle_session_exists(request: Request, exc: SessionAlreadyExists):
        return _error_response(
            request,
            status.HTTP_409_CONFLICT,
            "SESSION_EXISTS",
            "该匿名会话已存在，请使用新的会话 ID。",
        )

    @api.exception_handler(AuthServiceError)
    async def handle_auth_error(request: Request, exc: AuthServiceError):
        return _error_response(
            request,
            exc.status_code,
            exc.code,
            exc.message,
        )

    @api.exception_handler(ConversationNotFound)
    async def handle_conversation_not_found(request: Request, exc: ConversationNotFound):
        return _error_response(
            request,
            status.HTTP_404_NOT_FOUND,
            "CONVERSATION_NOT_FOUND",
            "对话上下文不存在或已经过期，请重新开始。",
        )

    @api.exception_handler(ConversationExpired)
    async def handle_conversation_expired(request: Request, exc: ConversationExpired):
        return _error_response(
            request,
            status.HTTP_410_GONE,
            "CONVERSATION_EXPIRED",
            "对话上下文已过期，请重新开始。",
        )

    @api.exception_handler(DraftNotFound)
    async def handle_draft_not_found(request: Request, exc: DraftNotFound):
        return _error_response(
            request,
            status.HTTP_404_NOT_FOUND,
            "DRAFT_NOT_FOUND",
            "自然语言草稿不存在或已经完成，请重新开始。",
        )

    @api.exception_handler(DraftExpired)
    async def handle_draft_expired(request: Request, exc: DraftExpired):
        return _error_response(
            request,
            status.HTTP_410_GONE,
            "DRAFT_EXPIRED",
            "自然语言草稿已过期，请重新开始。",
        )

    @api.exception_handler(DraftTurnLimit)
    async def handle_draft_turn_limit(request: Request, exc: DraftTurnLimit):
        return _error_response(
            request,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "DRAFT_TURN_LIMIT",
            "自然语言补充次数过多，请改用结构化表单或重新开始。",
        )

    @api.exception_handler(IntakeNotReady)
    async def handle_intake_not_ready(request: Request, exc: IntakeNotReady):
        return _error_response(
            request,
            status.HTTP_409_CONFLICT,
            "DRAFT_NOT_READY",
            "评估信息尚未补全，请先完成追问。",
        )

    @api.exception_handler(ToolNotFound)
    async def handle_tool_not_found(request: Request, exc: ToolNotFound):
        return _error_response(
            request,
            status.HTTP_404_NOT_FOUND,
            "TOOL_NOT_FOUND",
            "请求的工具不存在。",
        )

    @api.exception_handler(ToolArgumentError)
    async def handle_tool_argument_error(request: Request, exc: ToolArgumentError):
        return _error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "TOOL_ARGUMENT_ERROR",
            "工具参数不合法，run_risk_assessment 只接受 session_id。",
        )

    @api.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="studentriskguard-api",
            version=__version__,
        )

    @api.post(
        "/api/v1/sessions",
        response_model=SessionCreateResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["sessions"],
    )
    def create_session(payload: AssessmentRequest) -> SessionCreateResponse:
        record = store.create(payload)
        return SessionCreateResponse(
            session_id=payload.session_id,
            expires_at=record.expires_at,
            expires_in_seconds=store.ttl_seconds,
        )

    @api.get(
        "/api/v1/sessions/{session_id}",
        response_model=SessionMetadata,
        tags=["sessions"],
    )
    def get_session(session_id: str) -> SessionMetadata:
        record = store.get(session_id)
        request = record.request
        return SessionMetadata(
            session_id=request.session_id,
            created_at=record.created_at,
            expires_at=record.expires_at,
            debt_count=len(request.debts),
            subscription_count=len(request.recurring_subscriptions),
            forecast_months=request.forecast_months,
        )

    @api.delete(
        "/api/v1/sessions/{session_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["sessions"],
    )
    def delete_session(session_id: str) -> Response:
        store.delete(session_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @api.post(
        "/api/v1/assessments",
        response_model=AssessmentResult,
        tags=["assessment"],
    )
    def assess(payload: RunAssessmentRequest) -> AssessmentResult:
        return tool_executor.execute(
            RUN_RISK_ASSESSMENT_TOOL_NAME,
            {"session_id": payload.session_id},
        )

    @api.post(
        "/api/v1/agent/assess",
        response_model=AgentResponse,
        tags=["agent"],
    )
    def assess_with_agent(payload: RunAssessmentRequest) -> AgentResponse:
        return agent_runner.assess(payload.session_id)

    @api.post(
        "/api/v1/agent/intake",
        response_model=IntakeResponse,
        tags=["agent"],
    )
    def submit_intake(payload: NaturalLanguageIntakeRequest) -> IntakeResponse:
        return intake_service.submit(payload)

    @api.post(
        "/api/v1/agent/intake/{conversation_id}/confirm",
        response_model=AgentResponse,
        tags=["agent"],
    )
    def confirm_intake(
        conversation_id: str,
        payload: ConfirmIntakeRequest | None = None,
    ) -> AgentResponse:
        request = payload.assessment_request if payload is not None else None
        return intake_service.confirm(conversation_id, request)

    @api.post(
        "/api/v1/agent/chat",
        response_model=AgentChatResponse,
        tags=["agent"],
    )
    def chat(payload: AgentChatRequest) -> AgentChatResponse:
        return chat_orchestrator.chat(payload)

    @api.get(
        "/api/v1/education/topics",
        response_model=list[EducationCard],
        tags=["education"],
    )
    def list_education_topics() -> list[EducationCard]:
        return education.list_topics()

    @api.post(
        "/api/v1/tools/run_risk_assessment",
        response_model=AssessmentResult,
        tags=["tools"],
    )
    def run_risk_assessment_tool(payload: RunAssessmentRequest) -> AssessmentResult:
        return tool_executor.execute(
            RUN_RISK_ASSESSMENT_TOOL_NAME,
            {"session_id": payload.session_id},
        )

    @api.get("/api/v1/tools", tags=["tools"])
    def list_tools() -> list[dict]:
        return list(TOOL_DEFINITIONS)

    return api


app = create_app()

