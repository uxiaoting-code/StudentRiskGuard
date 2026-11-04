"""FastAPI adapter for StudentRiskGuard M3."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from riskguard import __version__
from riskguard.models import (
    ApiErrorDetail,
    ApiErrorResponse,
    AssessmentRequest,
    AssessmentResult,
    HealthResponse,
    RunAssessmentRequest,
    SessionCreateResponse,
    SessionMetadata,
)
from riskguard.services import (
    AssessmentService,
    SessionAlreadyExists,
    SessionExpired,
    SessionNotFound,
    SessionStore,
)
from riskguard.tools import (
    RUN_RISK_ASSESSMENT_TOOL,
    RUN_RISK_ASSESSMENT_TOOL_NAME,
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
) -> FastAPI:
    store = session_store if session_store is not None else SessionStore()
    assessment_service = AssessmentService(store)
    tool_executor = ToolExecutor(assessment_service)

    api = FastAPI(
        title="StudentRiskGuard API",
        version=__version__,
        description=(
            "大学生负债压力自检与理性消费科普 Agent。M3 提供匿名会话、"
            "确定性评估工具和 API；不提供授信或借贷功能。"
        ),
    )
    api.state.session_store = store
    api.state.assessment_service = assessment_service
    api.state.tool_executor = tool_executor

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
        return [RUN_RISK_ASSESSMENT_TOOL]

    return api


app = create_app()

