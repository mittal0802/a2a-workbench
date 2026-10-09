"""A deterministic stand-in LLM for tests: scripted policy, adapter, OpenAI-compatible server.

Policy, applied to the latest message:

- a user goal: call the first tool with ``{"message": <goal>}``;
- a tool result in ``input_required``: when the goal contains "ask me", reply
  ``Question from the agent: <question>``; otherwise call the same tool on the
  same task and context with ``{"message": "B"}``;
- ``auth_required``: reply ``Sign-in needed: <question>``;
- an error or rejected call: reply ``Failed: <message>``;
- anything else: reply ``Done: <first artifact text or message>``;
- a goal containing "loop forever" calls the first tool on every turn.

A user note carrying ``\\nResult: <json>`` is read like a tool result.
"""

import json
import uuid
from types import TracebackType
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a_workbench.core.assistant.llm import ChatMessage, LLMReply, ToolCall, ToolSpec, Usage
from a2a_workbench.fixtures.serve import ThreadServer

RESULT_MARKER = "\nResult: "


def _goal(history: list[ChatMessage]) -> str:
    for m in reversed(history):
        if m.role == "user" and RESULT_MARKER not in m.text:
            return m.text
    return ""


def _result(m: ChatMessage) -> dict[str, Any] | None:
    raw = m.text if m.role == "tool" else None
    if m.role == "user" and RESULT_MARKER in m.text:
        raw = m.text.split(RESULT_MARKER, 1)[1]
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": {"message": raw}}
    return value if isinstance(value, dict) else {"result": value}


def _first_output(result: dict[str, Any]) -> str:
    for artifact in result.get("artifacts") or []:
        for part in artifact.get("parts") or []:
            if part.get("text"):
                return str(part["text"])
            if part.get("data") is not None:
                return json.dumps(part["data"])
    messages = result.get("messages") or []
    return str(messages[-1]) if messages else ""


def _call(name: str, arguments: dict[str, Any]) -> LLMReply:
    return LLMReply(
        tool_calls=[ToolCall(id=f"call_{uuid.uuid4().hex[:12]}", name=name, arguments=arguments)],
        stop_reason="tool_calls",
    )


def scripted_reply(history: list[ChatMessage], tools: list[ToolSpec]) -> LLMReply:
    """Return the policy's next reply for ``history``."""
    goal = _goal(history)
    agent_tools = [t for t in tools if t.name.startswith("call_")] or tools
    first = agent_tools[0].name if agent_tools else None
    last = history[-1] if history else ChatMessage(role="user")
    result = _result(last)
    if first and "loop forever" in goal:
        return _call(first, {"message": "again"})
    if result is None:
        return _call(first, {"message": last.text}) if first else LLMReply(text="No agents.")
    if result.get("rejected") or result.get("error"):
        detail = result.get("rejected") or result.get("error") or {}
        return LLMReply(text=f"Failed: {detail.get('message', detail)}", stop_reason="stop")
    state = result.get("state")
    question = result.get("question") or ""
    if state == "input_required":
        if "ask me" in goal or not first:
            return LLMReply(text=f"Question from the agent: {question}", stop_reason="stop")
        name = next((m.tool_name for m in reversed(history) if m.tool_name), None) or first
        args = {"message": "B"}
        if result.get("task_id"):
            args["task_id"] = result["task_id"]
        if result.get("context_id"):
            args["context_id"] = result["context_id"]
        return _call(name, args)
    if state == "auth_required":
        return LLMReply(text=f"Sign-in needed: {question}", stop_reason="stop")
    return LLMReply(text=f"Done: {_first_output(result)}", stop_reason="stop")


def _usage(history: list[ChatMessage], reply: LLMReply) -> Usage:
    size = sum(len(m.text) + len(json.dumps([c.arguments for c in m.tool_calls])) for m in history)
    return Usage(input_tokens=max(1, size // 4), output_tokens=max(1, len(reply.text) // 4 + 5))


class ScriptedAdapter:
    """An ``LLMAdapter`` answering with ``scripted_reply``; ``calls`` counts completions."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> LLMReply:
        """Return the scripted reply with an approximate token usage."""
        self.calls += 1
        reply = scripted_reply(messages, tools)
        return reply.model_copy(update={"usage": _usage(messages, reply)})


def _from_openai(body: dict[str, Any]) -> tuple[list[ChatMessage], list[ToolSpec]]:
    names: dict[str, str] = {}
    history: list[ChatMessage] = []
    for m in body.get("messages", []):
        role = m.get("role")
        if role == "user":
            content = m.get("content")
            text = (
                content
                if isinstance(content, str)
                else "".join(p.get("text", "") for p in content or [])
            )
            history.append(ChatMessage(role="user", text=text))
        elif role == "assistant":
            calls = []
            for c in m.get("tool_calls") or []:
                names[c["id"]] = c["function"]["name"]
                calls.append(
                    ToolCall(
                        id=c["id"],
                        name=c["function"]["name"],
                        arguments=json.loads(c["function"].get("arguments") or "{}"),
                    )
                )
            history.append(
                ChatMessage(role="assistant", text=m.get("content") or "", tool_calls=calls)
            )
        elif role == "tool":
            history.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=m.get("tool_call_id"),
                    tool_name=names.get(m.get("tool_call_id", "")),
                    text=m.get("content") or "",
                )
            )
    tools = [
        ToolSpec(
            name=t["function"]["name"],
            description=t["function"].get("description", ""),
            input_schema=t["function"].get("parameters", {}),
        )
        for t in body.get("tools") or []
    ]
    return history, tools


def build_fake_openai_app(requests: list[dict[str, Any]]) -> Starlette:
    """Return an app serving ``POST /v1/chat/completions`` with ``scripted_reply``."""

    async def completions(request: Request) -> JSONResponse:
        if request.headers.get("authorization", "") in ("", "Bearer "):
            return JSONResponse({"error": {"message": "missing API key"}}, status_code=401)
        body = await request.json()
        requests.append(body)
        history, tools = _from_openai(body)
        reply = scripted_reply(history, tools)
        usage = _usage(history, reply)
        message: dict[str, Any] = {"role": "assistant", "content": reply.text or None}
        if reply.tool_calls:
            message["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in reply.tool_calls
            ]
        return JSONResponse(
            {
                "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion",
                "created": 0,
                "model": body.get("model", "scripted"),
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if reply.tool_calls else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": usage.input_tokens,
                    "completion_tokens": usage.output_tokens,
                    "total_tokens": usage.input_tokens + usage.output_tokens,
                },
            }
        )

    async def ready(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/v1/chat/completions", completions, methods=["POST"]),
            Route("/ready", ready),
        ]
    )


class FakeOpenAIServer(ThreadServer):
    """Serves the scripted LLM as an OpenAI-compatible API; ``base_url`` ends in ``/v1``."""

    def __init__(self, port: int | None = None) -> None:
        from a2a_workbench.fixtures.runner import free_port

        self.requests: list[dict[str, Any]] = []
        port = port or free_port()
        super().__init__(build_fake_openai_app(self.requests), port=port, ready_path="/ready")
        self.base_url = f"http://127.0.0.1:{port}/v1"

    def __enter__(self) -> "FakeOpenAIServer":
        self.start()
        return self

    def __exit__(
        self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.stop()
