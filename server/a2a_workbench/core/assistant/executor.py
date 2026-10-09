"""Runs one agent tool call as an ordinary Workbench conversation and summarizes the outcome."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import (
    AnyPartInput,
    DataPartInput,
    FilePartInput,
    TextPartInput,
)
from a2a_workbench.core.conversations.service import TERMINAL_STATES
from a2a_workbench.core.conversations.timeline import TimelineEvent
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.faults.profile import FaultProfile

OnEvent = Callable[[TimelineEvent], Awaitable[None]]
WAITING_STATES = frozenset({"input_required", "auth_required"})
SECTION_3_7 = (
    "A2A §3.7: results SHOULD be returned as artifacts; this agent completed the task "
    "with its output only in messages."
)


class ToolResult(BaseModel):
    """What one agent call produced, in the shape given back to the orchestrator."""

    agent: str
    conversation_id: str | None = None
    kind: Literal["message", "task", "error"]
    context_id: str | None = None
    task_id: str | None = None
    state: str | None = None
    question: str | None = None
    messages: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None

    def for_llm(self, shown_to_user: bool) -> str:
        """Return the JSON text handed to the model as the tool result.

        With ``shown_to_user``, the result says the agent's output was already
        shown to the user verbatim, so the model should not repeat it.
        """
        body = self.model_dump(exclude={"conversation_id"}, exclude_none=True)
        body["shown_to_user"] = shown_to_user
        if shown_to_user:
            body["note"] = "This output was already shown to the user verbatim; do not repeat it."
        return json.dumps(body, ensure_ascii=False)


def _texts(message: dict[str, Any] | None) -> list[str]:
    if not message:
        return []
    return [str(p["text"]) for p in message.get("parts", []) if p.get("text")]


def summarize_part(part: dict[str, Any]) -> dict[str, Any]:
    """Return a compact description of an A2A part (as JSON): text, data or file."""
    if "text" in part:
        return {"kind": "text", "text": part["text"]}
    if "data" in part:
        return {"kind": "data", "data": part["data"]}
    out: dict[str, Any] = {"kind": "file"}
    for key, name in (("url", "url"), ("filename", "name"), ("mediaType", "media_type")):
        if part.get(key):
            out[name] = part[key]
    if part.get("raw"):
        out["bytes"] = "inline (not shown)"
    return out


def summarize_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Return ``{"name", "artifact_id", "parts"}`` for an A2A artifact (as JSON)."""
    return {
        "name": artifact.get("name"),
        "artifact_id": artifact.get("artifactId"),
        "parts": [summarize_part(p) for p in artifact.get("parts", [])],
    }


def result_from_events(
    agent: str, conversation_id: str | None, events: list[TimelineEvent]
) -> ToolResult:
    """Fold a call's timeline events into a ``ToolResult``."""
    result = ToolResult(agent=agent, conversation_id=conversation_id, kind="task")
    artifacts: dict[str, dict[str, Any]] = {}
    saw_task = False
    last_status_text: str | None = None
    for e in events:
        result.context_id = e.context_id or result.context_id
        if e.task_id and e.kind in ("task", "status", "artifact"):
            result.task_id, saw_task = e.task_id, True
        if e.kind == "task":
            task = e.data.get("task", {})
            result.state = e.data.get("state", result.state)
            for a in task.get("artifacts", []) or []:
                artifacts[a.get("artifactId") or str(len(artifacts))] = a
            texts = _texts((task.get("status") or {}).get("message"))
            if texts:
                last_status_text = texts[-1]
                result.messages += [t for t in texts if t not in result.messages[-1:]]
        elif e.kind == "status":
            result.state = e.data.get("state", result.state)
            texts = _texts((e.data.get("status") or {}).get("message"))
            if texts:
                last_status_text = texts[-1]
                result.messages += [t for t in texts if t not in result.messages[-1:]]
        elif e.kind == "artifact":
            assembled = e.data.get("assembled") or e.data.get("artifact") or {}
            artifacts[assembled.get("artifactId") or str(len(artifacts))] = assembled
        elif e.kind == "message":
            result.messages += _texts(e.data.get("message"))
        elif e.kind in ("error", "connection_lost"):
            result.error = {k: v for k, v in e.data.items() if k not in ("task_id", "last_state")}
        elif e.kind == "recovered":
            result.error = None
            result.state = e.data.get("state_after", result.state)
    result.artifacts = [summarize_artifact(a) for a in artifacts.values()]
    if not saw_task:
        result.kind = "error" if result.error and not result.messages else "message"
    elif result.error and result.state not in TERMINAL_STATES | WAITING_STATES:
        result.kind = "error"
    if result.state in WAITING_STATES:
        result.question = last_status_text
    if result.state == "completed" and not result.artifacts and result.messages:
        result.warnings.append(SECTION_3_7)
    return result


def _parts(args: dict[str, Any]) -> list[AnyPartInput]:
    parts: list[AnyPartInput] = [TextPartInput(text=str(args.get("message", "")))]
    if args.get("data") is not None:
        parts.append(DataPartInput(data=args["data"]))
    for url in args.get("file_urls") or []:
        parts.append(FilePartInput(url=str(url)))
    return parts


class AgentCallExecutor:
    """Sends agent tool calls through ``ConversationService`` with exactly the given ids."""

    def __init__(self, wb: Any) -> None:
        self._wb = wb

    async def call(
        self,
        agent_id: str,
        args: dict[str, Any],
        *,
        conversation_id: str | None,
        timeout_s: float,
        on_event: OnEvent | None = None,
        faults: FaultProfile | None = None,
        extensions: list[str] | None = None,
        title: str | None = None,
    ) -> ToolResult:
        """Send one message and return what the agent did.

        A new conversation (``origin="assistant"``) is created when
        ``conversation_id`` is None. Streaming is used when the card declares
        it. A connection lost mid-task is recovered once with SubscribeToTask.
        After ``timeout_s`` the result carries the state reached so far.
        """
        agent = await self._wb.agents.get(agent_id)
        if conversation_id is None:
            conversation_id = (
                await self._wb.conversations.create(agent_id, title=title, origin="assistant")
            ).id
        streaming = bool(agent.card.get("capabilities", {}).get("streaming"))
        options = SendOptions(
            stream=streaming,
            inherit_ids=False,
            context_id=args.get("context_id"),
            task_id=args.get("task_id"),
            reference_task_ids=list(args.get("reference_task_ids") or []),
            accepted_output_modes=list(args.get("accepted_output_modes") or []),
            extensions=list(extensions or []),
            faults=faults,
        )
        events: list[TimelineEvent] = []
        notes: list[str] = []

        async def collect(stream: Any) -> None:
            async for event in stream:
                events.append(event)
                if on_event is not None and event.kind != "user_message":
                    await on_event(event)

        try:
            async with asyncio.timeout(timeout_s):
                await collect(self._wb.conversations.send(conversation_id, _parts(args), options))
                if events and events[-1].kind == "connection_lost":
                    notes.append(
                        "The stream dropped; resubscribed with SubscribeToTask (A2A §3.5.2)."
                    )
                    await collect(self._wb.conversations.resubscribe(conversation_id))
        except TimeoutError:
            notes.append(
                f"No final answer within {timeout_s:g} s; the task may still be running. "
                "Call get_task later to check it."
            )
        name = agent.name
        result = result_from_events(
            name, conversation_id, [e for e in events if e.kind != "user_message"]
        )
        result.notes = notes
        return result

    async def get_task(self, agent_id: str, task_id: str) -> ToolResult:
        """Return the task's current state via GetTask."""
        agent = await self._wb.agents.get(agent_id)
        try:
            task = await self._wb.tasks.get(agent_id, task_id)
        except AgentCallError as exc:
            return ToolResult(agent=agent.name, kind="error", task_id=task_id, error=exc.classified)
        return _from_task(agent.name, task)

    async def cancel_task(self, agent_id: str, task_id: str) -> ToolResult:
        """Ask the agent to cancel the task via CancelTask."""
        agent = await self._wb.agents.get(agent_id)
        try:
            task = await self._wb.tasks.cancel(agent_id, task_id)
        except AgentCallError as exc:
            return ToolResult(agent=agent.name, kind="error", task_id=task_id, error=exc.classified)
        return _from_task(agent.name, task)


def _from_task(agent: str, task: dict[str, Any]) -> ToolResult:
    event = TimelineEvent(
        conversation_id="",
        kind="task",
        task_id=task.get("id"),
        context_id=task.get("contextId"),
        data={"task": task, "state": task.get("state")},
    )
    return result_from_events(agent, None, [event])
