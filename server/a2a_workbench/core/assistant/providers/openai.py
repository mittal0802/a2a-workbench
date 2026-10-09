"""OpenAI Chat Completions adapter (also any OpenAI-compatible server)."""

import json
from typing import Any

import openai

from a2a_workbench.core.assistant.llm import (
    MAX_OUTPUT_TOKENS,
    ChatMessage,
    LLMError,
    LLMReply,
    ToolCall,
    ToolSpec,
    Usage,
    scrub_key,
)


def _messages(system: str, messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        if m.role == "user":
            out.append({"role": "user", "content": m.text})
        elif m.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.text or None}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in m.tool_calls
                ]
            out.append(msg)
        else:
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.text})
    return out


def _arguments(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_unparsed_arguments": raw}
    return value if isinstance(value, dict) else {"_unparsed_arguments": raw}


class OpenAIAdapter:
    """Completes through ``openai.AsyncOpenAI().chat.completions.create``."""

    def __init__(self, model: str, api_key: str, base_url: str | None = None) -> None:
        self._model = model
        self._key = api_key
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=1)

    async def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> LLMReply:
        """Send one chat completion request and translate the reply."""
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=_messages(system, messages),  # type: ignore[arg-type]
                max_completion_tokens=MAX_OUTPUT_TOKENS,
                **kwargs,
            )
        except openai.AuthenticationError as exc:
            raise LLMError("auth", scrub_key(_detail(exc), self._key)) from None
        except openai.RateLimitError as exc:
            raise LLMError("rate_limit", scrub_key(_detail(exc), self._key)) from None
        except openai.APIError as exc:
            raise LLMError("provider", scrub_key(_detail(exc), self._key)) from None
        choice = resp.choices[0]
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=_arguments(c.function.arguments))
            for c in (choice.message.tool_calls or [])
            if getattr(c, "function", None) is not None
        ]
        usage = resp.usage
        return LLMReply(
            text=choice.message.content or "",
            tool_calls=calls,
            usage=Usage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
            stop_reason=choice.finish_reason or "",
        )


def _detail(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        message = body.get("message") or (body.get("error") or {}).get("message")
        if message:
            return f"OpenAI: {message}"
    return f"OpenAI: {type(exc).__name__}"
