"""Service adapter over the frozen deterministic M2 core."""

from __future__ import annotations

from riskguard.core import run_assessment
from riskguard.models import AssessmentRequest, AssessmentResult
from riskguard.services.session_store import SessionStore


class AssessmentService:
    """Expose M2 calculations without duplicating any formulas."""

    def __init__(self, session_store: SessionStore) -> None:
        self._session_store = session_store

    def assess(self, request: AssessmentRequest) -> AssessmentResult:
        return run_assessment(request)

    def assess_session(self, session_id: str) -> AssessmentResult:
        record = self._session_store.get(session_id)
        return run_assessment(record.request)
