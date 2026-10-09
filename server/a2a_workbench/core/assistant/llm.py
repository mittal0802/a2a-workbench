"""Provider-neutral chat messages, tools and replies, and the adapter factory."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

Provider = Literal["anthropic", "openai", "gemini"]
PROVIDERS: tuple[Provider, ...] = ("anthropic", "openai", "gemini")
DEFAULT_MODELS: dict[str, str] = {"anthropic": "claude-sonnet-5-5"}
MAX_OUTPUT_TOKENS = 4096


class ToolSpec(BaseModel):
    """A function the model may call: name, description and JSON Schema of its arguments."""

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    """One function call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    signature: str | None = None
    """Opaque provider token that must be sent back with the call (Gemini thought signature)."""


class ChatMessage(BaseModel):
    """One turn of the conversation with the model.

    ``assistant`` turns may carry ``tool_calls``; ``tool`` turns answer one call
    (``tool_call_id``, ``tool_name``) with ``text``.
    """

    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_error: bool = False


class Usage(BaseModel):
    """Tokens the provider reports for one completion."""

    input_tokens: int = 0
    output_tokens: int = 0


class LLMReply(BaseModel):
    """The model's answer to one completion request."""

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    stop_reason: str = ""


class LLMError(Exception):
    """The provider refused or failed a request.

    ``category`` is ``auth`` (bad or missing key), ``rate_limit`` or ``provider``.
    The message never contains the API key.
    """

    def __init__(self, category: Literal["auth", "rate_limit", "provider"], message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


class LLMAdapter(Protocol):
    """Runs one completion against a provider."""

    async def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> LLMReply: ...


def sendable(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Drop turns providers reject: user turns without text, assistant turns with no content."""
    return [
        m
        for m in messages
        if not (m.role == "user" and not m.text.strip())
        and not (m.role == "assistant" and not m.text and not m.tool_calls)
    ]


def scrub_key(text: str, api_key: str) -> str:
    """Return ``text`` with ``api_key`` masked."""
    return text.replace(api_key, "••••") if api_key else text


def adapter_for(
    provider: str,
    model: str,
    api_key: str,
    base_url: str | None = None,
    recorder: Any = None,
) -> LLMAdapter:
    """Return the adapter for ``provider`` calling ``model`` with ``api_key``.

    ``base_url`` points the OpenAI adapter at an OpenAI-compatible server (and
    overrides the endpoint of the others). With ``recorder`` (an
    ``LLMRecorder``), every HTTP call the provider SDK makes is recorded.

    Raises:
        ValueError: for an unknown provider.
    """
    if provider == "anthropic":
        from a2a_workbench.core.assistant.providers.anthropic import AnthropicAdapter

        return AnthropicAdapter(model, api_key, base_url, recorder)
    if provider == "openai":
        from a2a_workbench.core.assistant.providers.openai import OpenAIAdapter

        return OpenAIAdapter(model, api_key, base_url, recorder)
    if provider == "gemini":
        from a2a_workbench.core.assistant.providers.gemini import GeminiAdapter

        return GeminiAdapter(model, api_key, base_url, recorder)
    raise ValueError(f"unknown provider '{provider}' (use one of {', '.join(PROVIDERS)})")
