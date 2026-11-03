"""Explainable four-dimension scorecard."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from riskguard.models import (
    AssessmentMetrics,
    AssessmentRequest,
    IrrResult,
    RiskAssessment,
    RiskDimension,
)


DEFAULT_SCORECARD_PATH = Path(__file__).with_name("scorecard.json")
REQUIRED_DIMENSION_IDS = {
    "debt_to_income",
    "debt_stack",
    "real_cost",
    "behavior_resilience",
}


def load_scorecard(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate a scorecard configuration."""

    config_path = Path(path) if path is not None else DEFAULT_SCORECARD_PATH
    with config_path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    validate_scorecard(config)
    return config


def validate_scorecard(config: Mapping[str, Any]) -> None:
    """Reject scorecard configurations that cannot produce a 0-100 score."""

    dimensions = config.get("dimensions")
    levels = config.get("risk_levels")
    if not isinstance(dimensions, list) or not dimensions:
        raise ValueError("scorecard dimensions must be a non-empty list")
    if not isinstance(levels, list) or not levels:
        raise ValueError("scorecard risk_levels must be a non-empty list")

    dimension_ids = {dimension.get("id") for dimension in dimensions}
    if dimension_ids != REQUIRED_DIMENSION_IDS:
        raise ValueError("scorecard must define the four frozen dimension ids")
    weight_sum = sum(float(dimension["weight"]) for dimension in dimensions)
    max_score_sum = sum(float(dimension["max_score"]) for dimension in dimensions)
    if not abs(weight_sum - 1.0) <= 1e-9:
        raise ValueError("scorecard dimension weights must sum to 1")
    if not abs(max_score_sum - 100.0) <= 1e-9:
        raise ValueError("scorecard dimension max scores must sum to 100")

    for dimension in dimensions:
        dimension_id = str(dimension.get("id"))
        if dimension_id == "behavior_resilience":
            rules = dimension.get("rules")
            if not isinstance(rules, dict):
                raise ValueError("behavior_resilience needs behavior rules")
            continue
        points = dimension.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError(f"dimension {dimension_id} needs at least two points")
        x_values = [float(point[0]) for point in points]
        y_values = [float(point[1]) for point in points]
        if x_values != sorted(x_values) or len(x_values) != len(set(x_values)):
            raise ValueError(f"dimension {dimension_id} points must be sorted")
        if min(y_values) < 0 or max(y_values) > float(dimension["max_score"]):
            raise ValueError(f"dimension {dimension_id} points exceed max score")
        if dimension.get("interpolation", "linear") not in {"linear", "step"}:
            raise ValueError(f"dimension {dimension_id} has unsupported interpolation")

    ordered_levels = sorted(levels, key=lambda item: int(item["min_score"]))
    expected_min = 0
    for level in ordered_levels:
        if int(level["min_score"]) != expected_min:
            raise ValueError("scorecard risk levels must cover 0-100 without gaps")
        expected_min = int(level["max_score"]) + 1
    if expected_min != 101:
        raise ValueError("scorecard risk levels must end at 100")


def interpolate_score(
    value: float,
    points: list[list[float]],
    method: str = "linear",
) -> float:
    """Score a value with either piecewise-linear or right-continuous steps."""

    numeric_points = [(float(x), float(y)) for x, y in points]
    if value <= numeric_points[0][0]:
        return numeric_points[0][1]
    if value >= numeric_points[-1][0]:
        return numeric_points[-1][1]
    if method == "step":
        score = numeric_points[0][1]
        for threshold, step_score in numeric_points:
            if value >= threshold:
                score = step_score
            else:
                break
        return score
    for (x0, y0), (x1, y1) in zip(numeric_points, numeric_points[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return y1
            ratio = (value - x0) / (x1 - x0)
            return y0 + (y1 - y0) * ratio
    return numeric_points[-1][1]


def _round_half_up(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _risk_level(score: int, levels: list[Mapping[str, Any]]) -> str:
    for level in levels:
        if int(level["min_score"]) <= score <= int(level["max_score"]):
            return str(level["level"])
    raise ValueError(f"risk score {score} is outside configured risk levels")


def _dimension_raw_value(
    dimension_id: str,
    request: AssessmentRequest,
    metrics: AssessmentMetrics,
    irr_results: list[IrrResult],
) -> float:
    if dimension_id == "debt_to_income":
        return metrics.debt_to_income_ratio
    if dimension_id == "debt_stack":
        return float(metrics.debt_count)
    if dimension_id == "real_cost":
        solved = [
            result.annualized_irr
            for result in irr_results
            if result.status == "ok" and result.annualized_irr is not None
        ]
        return max(solved, default=0.0)
    if dimension_id == "behavior_resilience":
        return 0.0
    raise ValueError(f"unknown risk dimension: {dimension_id}")


def compute_behavior_score(
    request: AssessmentRequest,
    scorecard: Mapping[str, Any],
) -> float:
    """Apply the behavior and resilience rules from scorecard.json."""

    dimension = next(
        item
        for item in scorecard["dimensions"]
        if item["id"] == "behavior_resilience"
    )
    rules = dimension["rules"]
    profile = request.behavior
    score = 0.0
    if profile.borrow_to_repay:
        score += float(rules["borrow_to_repay"])
    if profile.strict_overdue_count >= int(rules["strict_overdue_min_count"]):
        score += float(rules["strict_overdue"])
    score += float(rules["insufficient_month_points"][profile.insufficient_months_last_3])
    if profile.income_drop_30_cannot_cover:
        score += float(rules["income_drop_30_cannot_cover"])
    if (
        profile.financial_cognition_score is not None
        and profile.financial_cognition_score <= float(rules["cognitive_weak_threshold"])
    ):
        score += float(rules["cognitive_weak"])
    return min(score, float(dimension["max_score"]))


def compute_risk(
    request: AssessmentRequest,
    metrics: AssessmentMetrics,
    irr_results: list[IrrResult],
    scorecard: Mapping[str, Any] | None = None,
) -> RiskAssessment:
    """Score the four frozen dimensions and map the result to a risk level."""

    config = dict(scorecard) if scorecard is not None else load_scorecard()
    validate_scorecard(config)
    dimensions: list[RiskDimension] = []
    for item in config["dimensions"]:
        dimension_id = str(item["id"])
        raw_value = _dimension_raw_value(
            dimension_id, request, metrics, irr_results
        )
        if dimension_id == "behavior_resilience":
            score = compute_behavior_score(request, config)
        else:
            score = min(
                float(item["max_score"]),
                max(
                    0.0,
                    interpolate_score(
                        raw_value,
                        item["points"],
                        str(item.get("interpolation", "linear")),
                    ),
                ),
            )
        dimensions.append(
            RiskDimension(
                id=dimension_id,
                raw_value=round(raw_value, 8),
                score=round(score, 6),
                max_score=float(item["max_score"]),
                weight=float(item["weight"]),
                contribution=round(score, 6),
            )
        )

    total_score = _round_half_up(
        sum(dimension.contribution for dimension in dimensions)
    )
    ranked = sorted(
        dimensions,
        key=lambda dimension: (-dimension.contribution, dimension.id),
    )
    top_contributors = [
        dimension.id for dimension in ranked if dimension.contribution > 0
    ][:3]
    if not top_contributors:
        top_contributors = [ranked[0].id]

    return RiskAssessment(
        score=total_score,
        level=_risk_level(total_score, config["risk_levels"]),
        dimensions=dimensions,
        top_contributors=top_contributors,
    )
