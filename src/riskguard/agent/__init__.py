"""M4 interaction Agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from riskguard.agent.chat import ChatOrchestrator
    from riskguard.agent.deepseek import ChatModel, DeepSeekClient
    from riskguard.agent.intake import IntakeService
    from riskguard.agent.runner import AgentRunner

__all__ = [
    "AgentRunner",
    "ChatModel",
    "ChatOrchestrator",
    "DeepSeekClient",
    "IntakeService",
]


def __getattr__(name: str) -> Any:
    if name == "ChatOrchestrator":
        from riskguard.agent.chat import ChatOrchestrator

        return ChatOrchestrator
    if name in {"ChatModel", "DeepSeekClient"}:
        from riskguard.agent.deepseek import ChatModel, DeepSeekClient

        return {"ChatModel": ChatModel, "DeepSeekClient": DeepSeekClient}[name]
    if name == "IntakeService":
        from riskguard.agent.intake import IntakeService

        return IntakeService
    if name == "AgentRunner":
        from riskguard.agent.runner import AgentRunner

        return AgentRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
