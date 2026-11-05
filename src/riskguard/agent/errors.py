"""Agent-layer exceptions."""


class AgentError(Exception):
    """Base error for the interaction Agent."""


class LLMConfigurationError(AgentError):
    pass


class LLMRequestError(AgentError):
    pass


class LLMResponseError(AgentError):
    pass


class ToolCallMissing(AgentError):
    pass


class ExplanationInvalid(AgentError):
    pass
