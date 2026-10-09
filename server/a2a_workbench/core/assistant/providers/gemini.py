"""Google Gemini adapter (google-genai)."""

import base64
import json
import uuid
from typing import Any

from google import genai
from google.genai import errors, types

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


def _response(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"result": text}
    return value if isinstance(value, dict) else {"result": value}


def _contents(messages: list[ChatMessage]) -> list[types.Content]:
    out: list[types.Content] = []
    for m in messages:
        if m.role == "user":
            out.append(types.Content(role="user", parts=[types.Part(text=m.text)]))
        elif m.role == "assistant":
            parts = [types.Part(text=m.text)] if m.text else []
            parts += [
                types.Part(
                    function_call=types.FunctionCall(id=c.id, name=c.name, args=c.arguments),
                    thought_signature=base64.b64decode(c.signature) if c.signature else None,
                )
                for c in m.tool_calls
            ]
            out.append(types.Content(role="model", parts=parts))
        else:
            part = types.Part(
                function_response=types.FunctionResponse(
                    id=m.tool_call_id, name=m.tool_name or "", response=_response(m.text)
                )
            )
            if (
                out
                and out[-1].role == "user"
                and out[-1].parts
                and out[-1].parts[0].function_response
            ):
                out[-1].parts.append(part)
            else:
                out.append(types.Content(role="user", parts=[part]))
    return out


class GeminiAdapter:
    """Completes through ``genai.Client().aio.models.generate_content``."""

    def __init__(self, model: str, api_key: str, base_url: str | None = None) -> None:
        self._model = model
        self._key = api_key
        options = types.HttpOptions(base_url=base_url) if base_url else None
        self._client = genai.Client(api_key=api_key, http_options=options)

    async def aclose(self) -> None:
        """Close the provider client's connections."""
        await self._client.aio.aclose()

    async def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> LLMReply:
        """Send one generateContent request and translate the reply."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters_json_schema=t.input_schema,
                        )
                        for t in tools
                    ]
                )
            ]
            if tools
            else None,
        )
        try:
            resp = await self._client.aio.models.generate_content(
                model=self._model, contents=_contents(messages), config=config
            )
        except errors.ClientError as exc:
            category = (
                "auth"
                if exc.code in (401, 403)
                else "rate_limit"
                if exc.code == 429
                else "provider"
            )
            raise LLMError(category, scrub_key(f"Gemini: {exc.message}", self._key)) from None  # type: ignore[arg-type]
        except errors.APIError as exc:
            raise LLMError("provider", scrub_key(f"Gemini: {exc.message}", self._key)) from None
        parts = (
            resp.candidates[0].content.parts
            if resp.candidates and resp.candidates[0].content
            else None
        ) or []
        text = "".join(p.text for p in parts if p.text)
        calls = [
            ToolCall(
                id=p.function_call.id or uuid.uuid4().hex,
                name=p.function_call.name or "",
                arguments=dict(p.function_call.args or {}),
                signature=base64.b64encode(p.thought_signature).decode()
                if p.thought_signature
                else None,
            )
            for p in parts
            if p.function_call
        ]
        meta = resp.usage_metadata
        finish = resp.candidates[0].finish_reason if resp.candidates else None
        return LLMReply(
            text=text,
            tool_calls=calls,
            usage=Usage(
                input_tokens=(meta.prompt_token_count or 0) if meta else 0,
                output_tokens=(meta.candidates_token_count or 0) if meta else 0,
            ),
            stop_reason=str(finish.value if finish else ""),
        )
