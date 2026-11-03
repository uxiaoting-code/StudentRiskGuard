"""FastAPI adapter for the StudentRiskGuard MVP."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from riskguard import __version__


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["studentriskguard-api"]
    version: str


app = FastAPI(
    title="StudentRiskGuard API",
    version=__version__,
    description=(
        "大学生负债压力自检与理性消费科普 Agent。"
        "当前 M1 仅提供健康检查，不提供授信或借贷功能。"
    ),
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Return a minimal liveness response used by local and deployment checks."""

    return HealthResponse(
        status="ok",
        service="studentriskguard-api",
        version=__version__,
    )
