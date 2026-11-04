from __future__ import annotations

import json
from pathlib import Path

import pytest

from riskguard.models import AssessmentRequest, AssessmentResult
from riskguard.services import AssessmentService, SessionStore
from riskguard.tools import (
    RUN_RISK_ASSESSMENT_TOOL,
    RUN_RISK_ASSESSMENT_TOOL_NAME,
    ToolArgumentError,
    ToolExecutor,
    ToolNotFound,
)

ROOT = Path(__file__).resolve().parents[1]


def demo_request(sample_id: str = "S-03") -> AssessmentRequest:
    cases = json.loads((ROOT / "contracts" / "demo_cases.json").read_text(encoding="utf-8"))
    raw = next(case["request"] for case in cases if case["sample_id"] == sample_id)
    return AssessmentRequest.model_validate(raw)


def executor_for(session_id: str = "tool-session") -> tuple[ToolExecutor, AssessmentRequest]:
    store = SessionStore()
    request = demo_request("S-03").model_copy(update={"session_id": session_id})
    store.create(request)
    service = AssessmentService(store)
    return ToolExecutor(service), request


def test_tool_definition_contains_only_session_id() -> None:
    parameter_names = set(
        RUN_RISK_ASSESSMENT_TOOL["function"]["parameters"]["properties"]
    )
    assert parameter_names == {"session_id"}


def test_run_risk_assessment_returns_complete_result() -> None:
    executor, request = executor_for()

    result = executor.execute(
        RUN_RISK_ASSESSMENT_TOOL_NAME,
        {"session_id": request.session_id},
    )

    assert isinstance(result, AssessmentResult)
    assert result.risk.level == "中风险"
    assert result.model_version == "calc-2026.11-m2-final"
    assert len(result.cashflow_series) == 12


def test_tool_rejects_unknown_tool() -> None:
    executor, _ = executor_for()

    with pytest.raises(ToolNotFound):
        executor.execute("unknown_tool", {"session_id": "tool-session"})


def test_tool_rejects_raw_financial_arguments() -> None:
    executor, request = executor_for()

    with pytest.raises(ToolArgumentError):
        executor.execute(
            RUN_RISK_ASSESSMENT_TOOL_NAME,
            {"session_id": request.session_id, "income": {"amount": 3000}},
        )
