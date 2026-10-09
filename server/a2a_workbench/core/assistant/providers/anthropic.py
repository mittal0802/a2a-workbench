"""Anthropic Messages API adapter."""

import json
from typing import Any

import anthropic

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


def _messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "user":
            out.append({"role": "user", "content": [{"type": "text", "text": m.text}]})
        elif m.role == "assistant":
            content: list[dict[str, Any]] = []
            if m.text:
                content.append({"type": "text", "text": m.text})
            content += [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                for c in m.tool_calls
            ]
            out.append({"role": "assistant", "content": content})
        else:
            block = {
                "type": "tool_result",
                "tool_use_id": m.tool_call_id,
                "content": m.text,
                "is_error": m.is_error,
            }
            if out and out[-1]["role"] == "user" and out[-1]["content"][0]["type"] == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


class AnthropicAdapter:
    """Completes through ``anthropic.AsyncAnthropic().messages.create``."""

    def __init__(self, model: str, api_key: str, base_url: str | None = None) -> None:
        self._model = model
        self._key = api_key
        self._client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url, max_retries=1)

    async def aclose(self) -> None:
        """Close the provider client's connections."""
        await self._client.close()

    async def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> LLMReply:
        """Send one Messages request and translate the reply."""
        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=_messages(messages),  # type: ignore[arg-type]
                tools=[
                    {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                    for t in tools
                ],  # type: ignore[arg-type]
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("auth", scrub_key(_detail(exc), self._key)) from None
        except anthropic.RateLimitError as exc:
            raise LLMError("rate_limit", scrub_key(_detail(exc), self._key)) from None
        except anthropic.APIError as exc:
            raise LLMError("provider", scrub_key(_detail(exc), self._key)) from None
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))  # type: ignore[union-attr]
            for b in resp.content
            if b.type == "tool_use"
        ]
        return LLMReply(
            text=text,
            tool_calls=calls,
            usage=Usage(
                input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens
            ),
            stop_reason=resp.stop_reason or "",
        )


def _detail(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return f"Anthropic: {err['message']}"
        return f"Anthropic: {json.dumps(body)[:300]}"
    return f"Anthropic: {type(exc).__name__}"
