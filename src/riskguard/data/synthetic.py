"""Load the frozen demonstration requests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from riskguard.models import AssessmentRequest


DEFAULT_DEMO_CASES_PATH = (
    Path(__file__).resolve().parents[3] / "contracts" / "demo_cases.json"
)


def load_demo_cases(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load demonstration cases from the frozen contract file."""

    source = Path(path) if path is not None else DEFAULT_DEMO_CASES_PATH
    with source.open(encoding="utf-8") as handle:
        cases = json.load(handle)
    if not isinstance(cases, list):
        raise ValueError("demo cases must be a JSON list")
    return cases


def demo_requests(path: str | Path | None = None) -> list[AssessmentRequest]:
    """Return typed requests for all demonstration cases."""

    return [
        AssessmentRequest.model_validate(case["request"])
        for case in load_demo_cases(path)
    ]
