"""Assistant sessions: the orchestrator run loop, response modes, limits and pauses."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.assistant.executor import (
    AgentCallExecutor,
    ToolResult,
    summarize_artifact,
    summarize_part,
)
from a2a_workbench.core.assistant.keys import ENV_VARS
from a2a_workbench.core.assistant.llm import (
    DEFAULT_MODELS,
    PROVIDERS,
    ChatMessage,
    LLMAdapter,
    LLMError,
    ToolCall,
    adapter_for,
)
from a2a_workbench.core.assistant.prompt import RESULT_MARKER, SYSTEM_PROMPT
from a2a_workbench.core.assistant.tools import (
    AgentTool,
    CallRejected,
    SessionIds,
    build_tools,
    validate_call,
)
from a2a_workbench.core.conversations.timeline import TimelineEvent
from a2a_workbench.core.store.models import (
    DEFAULT_WORKSPACE_ID,
    AssistantSession,
    AssistantStepRow,
)

ResponseMode = Literal["rewrite", "pass_through"]
Status = Literal["idle", "running", "awaiting_user", "awaiting_sign_in", "stopped"]
StepKind = Literal[
    "user",
    "assistant",
    "tool_call",
    "rejected_call",
    "tool_result",
    "agent_output",
    "paused",
    "resumed",
    "limit",
    "error",
    "done",
]
AdapterFactory = Callable[..., LLMAdapter]


class Limits(BaseModel):
    """Bounds of one user turn: model calls, time per agent call and per turn, tokens."""

    max_steps: int = Field(default=12, ge=1, le=100)
    call_timeout_s: float = Field(default=120, gt=0)
    run_timeout_s: float = Field(default=600, gt=0)
    token_budget: int = Field(default=200_000, ge=1)


class SessionIn(BaseModel):
    """A new Assistant chat."""

    provider: str
    model: str | None = None
    response_mode: ResponseMode = "rewrite"
    agent_ids: list[str]
    limits: Limits = Field(default_factory=Limits)
    title: str | None = None


class SessionOut(BaseModel):
    """An Assistant chat as shown to clients."""

    id: str
    title: str
    provider: str
    model: str
    response_mode: ResponseMode
    agent_ids: list[str]
    limits: Limits
    status: Status
    pending: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class Step(BaseModel):
    """One entry of an Assistant chat's timeline."""

    session_id: str
    seq: int
    kind: StepKind
    ts: datetime
    data: dict[str, Any]


class SessionNotFoundError(LookupError):
    """No Assistant chat has this id."""


class TurnInProgressError(RuntimeError):
    """A turn or resume is already running for this Assistant chat."""


def _out(row: AssistantSession) -> SessionOut:
    return SessionOut(
        id=row.id,
        title=row.title,
        provider=row.provider,
        model=row.model,
        response_mode=row.response_mode,  # type: ignore[arg-type]
        agent_ids=list(row.agent_ids or []),
        limits=Limits(**(row.limits or {})),
        status=row.status,  # type: ignore[arg-type]
        pending=row.pending,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _step(row: AssistantStepRow) -> Step:
    return Step(
        session_id=row.session_id,
        seq=row.seq,
        kind=row.kind,
        ts=row.ts,
        data=row.data,  # type: ignore[arg-type]
    )


class AssistantService:
    """Runs Assistant chats: each user turn loops model → agent calls → model until done.

    Steps are stored and published as ``{"type": "step", "step": ...}`` on
    ``assistant:<id>``. One turn runs at a time per chat.
    """

    def __init__(
        self,
        wb: Any,
        *,
        adapter_factory: AdapterFactory = adapter_for,
        watch_interval_s: float = 3.0,
    ) -> None:
        self._wb = wb
        self._adapters = adapter_factory
        self._executor = AgentCallExecutor(wb)
        self._watch_interval = watch_interval_s
        self._busy: set[str] = set()
        self._running: dict[str, asyncio.Task[None]] = {}
        self._watchers: dict[str, asyncio.Task[None]] = {}
        self._sinks: dict[str, list[asyncio.Queue[Step | None]]] = {}

    # ----- sessions -------------------------------------------------------

    async def create(self, body: SessionIn) -> SessionOut:
        """Start a chat with the given provider, model, agents and response mode.

        Raises:
            ValueError: for an unknown provider, a missing model, or no agents.
            AgentNotFoundError: if an agent id is not registered.
        """
        if body.provider not in PROVIDERS:
            raise ValueError(f"unknown provider '{body.provider}'")
        model = body.model or DEFAULT_MODELS.get(body.provider)
        if not model:
            raise ValueError(f"choose a model for {body.provider}")
        if not body.agent_ids:
            raise ValueError("choose at least one agent")
        for agent_id in body.agent_ids:
            await self._wb.agents.get(agent_id)
        row = AssistantSession(
            workspace_id=DEFAULT_WORKSPACE_ID,
            title=body.title or "New chat",
            provider=body.provider,
            model=model,
            response_mode=body.response_mode,
            agent_ids=list(body.agent_ids),
            limits=body.limits.model_dump(),
            transcript=[],
            ids={},
            contexts={},
        )
        async with self._wb.db.sessions() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _out(row)

    async def _load(self, sid: str) -> AssistantSession:
        async with self._wb.db.sessions() as session:
            row = await session.get(AssistantSession, sid)
        if row is None:
            raise SessionNotFoundError(f"assistant chat {sid} not found")
        return row

    async def _save(self, sid: str, **fields: Any) -> AssistantSession:
        async with self._wb.db.sessions() as session:
            row = await session.get(AssistantSession, sid)
            if row is None:
                raise SessionNotFoundError(f"assistant chat {sid} not found")
            for key, value in fields.items():
                setattr(row, key, value)
            await session.commit()
            await session.refresh(row)
        return row

    async def get(self, sid: str) -> SessionOut:
        """Return the chat.

        Raises:
            SessionNotFoundError: if it does not exist.
        """
        return _out(await self._load(sid))

    async def list(self) -> list[SessionOut]:
        """Return every chat, newest first."""
        async with self._wb.db.sessions() as session:
            rows = (
                await session.execute(
                    select(AssistantSession).order_by(AssistantSession.updated_at.desc())
                )
            ).scalars()
            return [_out(r) for r in rows]

    async def steps(self, sid: str, after_seq: int = 0) -> list[Step]:
        """Return the chat's steps with ``seq`` greater than ``after_seq``, in order."""
        await self._load(sid)
        async with self._wb.db.sessions() as session:
            rows = (
                await session.execute(
                    select(AssistantStepRow)
                    .where(AssistantStepRow.session_id == sid, AssistantStepRow.seq > after_seq)
                    .order_by(AssistantStepRow.seq)
                )
            ).scalars()
            return [_step(r) for r in rows]

    async def update(
        self,
        sid: str,
        *,
        response_mode: ResponseMode | None = None,
        agent_ids: list[str] | None = None,
        title: str | None = None,
    ) -> SessionOut:
        """Change the response mode, the agents in use or the title; later turns use them."""
        fields: dict[str, Any] = {}
        if response_mode is not None:
            fields["response_mode"] = response_mode
        if agent_ids is not None:
            if not agent_ids:
                raise ValueError("choose at least one agent")
            for agent_id in agent_ids:
                await self._wb.agents.get(agent_id)
            fields["agent_ids"] = list(agent_ids)
        if title is not None:
            fields["title"] = title
        return _out(await self._save(sid, **fields))

    # ----- streaming plumbing --------------------------------------------

    async def _emit(self, sid: str, kind: StepKind, data: dict[str, Any]) -> Step:
        async with self._wb.db.sessions() as session:
            row = await session.get(AssistantSession, sid)
            assert row is not None
            row.last_seq += 1
            step_row = AssistantStepRow(session_id=sid, seq=row.last_seq, kind=kind, data=data)
            session.add(step_row)
            await session.commit()
            await session.refresh(step_row)
        step = _step(step_row)
        self._wb.bus.publish(
            f"assistant:{sid}", {"type": "step", "step": step.model_dump(mode="json")}
        )
        for queue in self._sinks.get(sid, []):
            queue.put_nowait(step)
        return step

    def _start(self, sid: str, work: Callable[[], Awaitable[None]]) -> AsyncIterator[Step]:
        """Claim the chat and start ``work`` now; return an iterator over its steps.

        Raises:
            TurnInProgressError: if a turn or resume is already running for the chat.
        """
        if sid in self._busy:
            raise TurnInProgressError(f"assistant chat {sid} is already running a turn")
        self._busy.add(sid)
        queue: asyncio.Queue[Step | None] = asyncio.Queue()
        self._sinks.setdefault(sid, []).append(queue)

        async def run() -> None:
            try:
                await self._load(sid)
                await work()
            except asyncio.CancelledError:
                await asyncio.shield(self._stopped(sid))
            except SessionNotFoundError:
                raise
            except Exception as exc:
                await self._save(sid, status="idle")
                await self._emit(sid, "error", {"category": "workbench", "message": f"{exc}"[:500]})
            finally:
                self._sinks[sid].remove(queue)
                self._busy.discard(sid)
                if self._running.get(sid) is task:
                    self._running.pop(sid, None)

        task = asyncio.ensure_future(run())
        task.add_done_callback(lambda _: queue.put_nowait(None))
        self._running[sid] = task
        return self._drain(queue, task)

    async def _stopped(self, sid: str) -> None:
        await self._save(sid, status="stopped", pending=None)
        await self._emit(sid, "limit", {"limit": "stopped", "message": "Stopped."})

    @staticmethod
    async def _drain(
        queue: asyncio.Queue[Step | None], task: asyncio.Task[None]
    ) -> AsyncIterator[Step]:
        while (step := await queue.get()) is not None:
            yield step
        if not task.cancelled() and task.exception() is not None:
            raise task.exception()  # type: ignore[misc]

    def busy(self, sid: str) -> bool:
        """Whether a turn or resume is running for the chat."""
        return sid in self._busy

    def send(self, sid: str, text: str) -> AsyncIterator[Step]:
        """Start one user turn and return an iterator over its steps.

        While the chat awaits the user's answer to an agent question
        (pass-through), ``text`` goes straight to that agent on the same task.

        Raises:
            TurnInProgressError: if a turn is already running for the chat.
            SessionNotFoundError: (when iterating) if the chat does not exist.
        """
        return self._start(sid, lambda: self._turn(sid, text))

    def resume(self, sid: str) -> AsyncIterator[Step]:
        """Continue a chat paused for sign-in: read the task with GetTask and carry on.

        Raises:
            TurnInProgressError: if a turn is already running for the chat.
        """
        return self._start(sid, lambda: self._resume(sid))

    async def stop(self, sid: str) -> None:
        """Cancel the running turn (if any) and any sign-in watch; the chat becomes ``stopped``."""
        watcher = self._watchers.pop(sid, None)
        if watcher:
            watcher.cancel()
        task = self._running.get(sid)
        if task and not task.done():
            task.cancel()
            return
        row = await self._load(sid)
        if row.status in ("awaiting_user", "awaiting_sign_in"):
            await self._save(sid, status="stopped", pending=None)
            await self._emit(sid, "limit", {"limit": "stopped", "message": "Stopped."})

    async def close(self) -> None:
        """Cancel every running turn and watcher."""
        for task in [*self._watchers.values(), *self._running.values()]:
            task.cancel()
        for task in [*self._watchers.values(), *self._running.values()]:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._watchers.clear()
        self._running.clear()

    # ----- the turn -------------------------------------------------------

    async def _append(self, sid: str, *messages: ChatMessage) -> None:
        row = await self._load(sid)
        transcript = list(row.transcript or []) + [m.model_dump() for m in messages]
        await self._save(sid, transcript=transcript)

    async def _turn(self, sid: str, text: str) -> None:
        row = await self._load(sid)
        if row.status == "awaiting_user" and row.pending:
            await self._save(sid, status="running")
            await self._emit(sid, "user", {"text": text, "to_agent": row.pending.get("agent")})
            if not await self._direct_reply(sid, text):
                return
        else:
            await self._save(sid, status="running", pending=None)
            await self._emit(sid, "user", {"text": text})
            await self._append(sid, ChatMessage(role="user", text=text))
        await self._loop(sid)

    async def _adapter(self, row: AssistantSession) -> LLMAdapter | None:
        found = await self._wb.provider_keys.get(row.provider)
        if found is None:
            env = " or ".join(ENV_VARS.get(row.provider, ()))
            await self._save(row.id, status="idle")
            await self._emit(
                row.id,
                "error",
                {
                    "category": "auth",
                    "message": f"No API key for {row.provider}. Add one in the Assistant "
                    f"settings or set {env}.",
                },
            )
            return None
        key, base_url = found
        return self._adapters(row.provider, row.model, key, base_url)

    async def _tools(self, row: AssistantSession) -> list[AgentTool]:
        agents = [await self._wb.agents.get(a) for a in row.agent_ids]
        return build_tools(agents)

    async def _loop(self, sid: str) -> None:
        row = await self._load(sid)
        limits = Limits(**(row.limits or {}))
        adapter = await self._adapter(row)
        if adapter is None:
            return
        try:
            await self._loop_with(sid, adapter, limits)
        finally:
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()

    async def _loop_with(self, sid: str, adapter: LLMAdapter, limits: Limits) -> None:
        row = await self._load(sid)
        tools = await self._tools(row)
        started, tokens = time.monotonic(), 0
        for _ in range(limits.max_steps):
            remaining = limits.run_timeout_s - (time.monotonic() - started)
            if remaining <= 0:
                await self._limit(sid, "run_timeout", limits.run_timeout_s)
                return
            if tokens >= limits.token_budget:
                await self._limit(sid, "token_budget", limits.token_budget)
                return
            row = await self._load(sid)
            history = [ChatMessage(**m) for m in row.transcript or []]
            try:
                reply = await asyncio.wait_for(
                    adapter.complete(SYSTEM_PROMPT, history, [t.spec for t in tools]), remaining
                )
            except LLMError as exc:
                await self._save(sid, status="idle")
                await self._emit(sid, "error", {"category": exc.category, "message": exc.message})
                return
            except TimeoutError:
                await self._limit(sid, "run_timeout", limits.run_timeout_s)
                return
            tokens += reply.usage.input_tokens + reply.usage.output_tokens
            await self._append(
                sid, ChatMessage(role="assistant", text=reply.text, tool_calls=reply.tool_calls)
            )
            await self._emit(
                sid,
                "assistant",
                {
                    "text": reply.text,
                    "tool_calls": [c.model_dump() for c in reply.tool_calls],
                    "usage": reply.usage.model_dump(),
                    "tokens_used": tokens,
                },
            )
            if not reply.tool_calls:
                await self._save(sid, status="idle")
                await self._emit(sid, "done", {"text": reply.text})
                return
            if await self._calls(sid, tools, reply.tool_calls, limits):
                return
        await self._limit(sid, "max_steps", limits.max_steps)

    async def _limit(self, sid: str, name: str, value: float) -> None:
        await self._save(sid, status="idle")
        await self._emit(sid, "limit", {"limit": name, "value": value})

    async def _run_calls(self, sid: str, calls: list[dict[str, Any]]) -> AsyncIterator[Step]:
        """Run tool calls as if the model had requested them (for tests and replays)."""

        async def work() -> None:
            row = await self._load(sid)
            tool_calls = [
                ToolCall(id=f"manual_{i}", name=c["name"], arguments=c.get("arguments", {}))
                for i, c in enumerate(calls)
            ]
            await self._append(sid, ChatMessage(role="assistant", tool_calls=tool_calls))
            await self._calls(sid, await self._tools(row), tool_calls, Limits(**row.limits))

        async for step in self._start(sid, work):
            yield step

    async def _calls(
        self, sid: str, tools: list[AgentTool], calls: list[ToolCall], limits: Limits
    ) -> bool:
        """Run the model's tool calls in order; return True when the chat paused.

        Every call gets a tool message, even when the turn is stopped or fails
        part-way, so the transcript stays valid for the next request.
        """
        answered: set[str] = set()
        try:
            return await self._run_each(sid, tools, calls, limits, answered)
        finally:
            missing = [c for c in calls if c.id not in answered]
            if missing:
                await asyncio.shield(
                    self._append(
                        sid,
                        *[
                            ChatMessage(
                                role="tool",
                                tool_call_id=c.id,
                                tool_name=c.name,
                                is_error=True,
                                text=json.dumps(
                                    {"error": "not completed: the turn was interrupted"}
                                ),
                            )
                            for c in missing
                        ],
                    )
                )

    async def _run_each(
        self,
        sid: str,
        tools: list[AgentTool],
        calls: list[ToolCall],
        limits: Limits,
        answered: set[str],
    ) -> bool:
        for i, call in enumerate(calls):
            message, pause = await self._one_call(sid, tools, call, limits)
            await self._append(sid, message)
            answered.add(call.id)
            if pause:
                skipped = [
                    ChatMessage(
                        role="tool",
                        tool_call_id=c.id,
                        tool_name=c.name,
                        is_error=True,
                        text=json.dumps({"skipped": "not run: the chat paused for the user"}),
                    )
                    for c in calls[i + 1 :]
                ]
                if skipped:
                    await self._append(sid, *skipped)
                    answered.update(c.id for c in calls[i + 1 :])
                await self._pause(sid, pause)
                return True
        return False

    async def _pause(self, sid: str, pause: dict[str, Any]) -> None:
        status = "awaiting_sign_in" if pause["reason"] == "auth_required" else "awaiting_user"
        await self._save(sid, status=status, pending=pause)
        await self._emit(sid, "paused", pause)
        if status == "awaiting_sign_in":
            old = self._watchers.pop(sid, None)
            if old:
                old.cancel()
            self._watchers[sid] = asyncio.ensure_future(self._watch(sid, pause))

    def _pass_through(self, sid: str, agent_id: str, agent: str, conversation_id: list[str]) -> Any:
        async def on_event(e: TimelineEvent) -> None:
            base = {"agent": agent, "agent_id": agent_id, "conversation_id": conversation_id[0]}
            if e.kind == "status":
                message = (e.data.get("status") or {}).get("message")
                parts = [summarize_part(p) for p in (message or {}).get("parts", [])]
                if parts:
                    await self._emit(
                        sid,
                        "agent_output",
                        {**base, "source": "status", "state": e.data.get("state"), "parts": parts},
                    )
            elif e.kind == "artifact":
                chunk = e.data.get("artifact") or {}
                await self._emit(
                    sid,
                    "agent_output",
                    {
                        **base,
                        "source": "artifact",
                        "artifact_id": chunk.get("artifactId"),
                        "name": chunk.get("name"),
                        "append": e.data.get("append", False),
                        "last_chunk": e.data.get("last_chunk", False),
                        "parts": [summarize_part(p) for p in chunk.get("parts", [])],
                    },
                )
            elif e.kind == "message":
                parts = [summarize_part(p) for p in (e.data.get("message") or {}).get("parts", [])]
                await self._emit(sid, "agent_output", {**base, "source": "message", "parts": parts})
            elif e.kind == "task":
                task = e.data.get("task") or {}
                message = (task.get("status") or {}).get("message")
                if message:
                    parts = [summarize_part(p) for p in message.get("parts", [])]
                    await self._emit(
                        sid,
                        "agent_output",
                        {**base, "source": "status", "state": e.data.get("state"), "parts": parts},
                    )
                for artifact in task.get("artifacts") or []:
                    summary = summarize_artifact(artifact)
                    await self._emit(
                        sid,
                        "agent_output",
                        {
                            **base,
                            "source": "artifact",
                            "artifact_id": summary["artifact_id"],
                            "name": summary["name"],
                            "append": False,
                            "last_chunk": True,
                            "parts": summary["parts"],
                        },
                    )

        return on_event

    def _decide(
        self, row: AssistantSession, agent_id: str, tool: str, result: ToolResult
    ) -> dict[str, Any] | None:
        base = {
            "agent_id": agent_id,
            "agent": result.agent,
            "tool": tool,
            "conversation_id": result.conversation_id,
            "task_id": result.task_id,
            "context_id": result.context_id,
            "question": result.question,
        }
        if result.state == "auth_required":
            return {**base, "reason": "auth_required"}
        if result.state == "input_required" and row.response_mode == "pass_through":
            return {**base, "reason": "input_required"}
        return None

    async def _record(self, sid: str, agent_id: str, result: ToolResult) -> None:
        if result.kind == "error":
            return
        row = await self._load(sid)
        ids = SessionIds(row.ids)
        ids.record(agent_id, result.context_id, result.task_id, result.state)
        contexts = dict(row.contexts or {})
        if result.context_id and result.conversation_id:
            contexts.setdefault(agent_id, {})[result.context_id] = result.conversation_id
        await self._save(sid, ids=ids.dump(), contexts=contexts)

    async def _execute(
        self,
        sid: str,
        row: AssistantSession,
        agent_id: str,
        args: dict[str, Any],
        conversation_id: str | None,
        limits: Limits,
    ) -> ToolResult:
        agent = await self._wb.agents.get(agent_id)
        holder = [conversation_id or ""]
        on_event = None
        if row.response_mode == "pass_through":
            on_event = self._pass_through(sid, agent_id, agent.name, holder)
        if conversation_id is None:
            conversation_id = (
                await self._wb.conversations.create(agent_id, title=row.title, origin="assistant")
            ).id
            holder[0] = conversation_id
        result = await self._executor.call(
            agent_id,
            args,
            conversation_id=conversation_id,
            timeout_s=limits.call_timeout_s,
            on_event=on_event,
        )
        await self._record(sid, agent_id, result)
        return result

    async def _one_call(
        self, sid: str, tools: list[AgentTool], call: ToolCall, limits: Limits
    ) -> tuple[ChatMessage, dict[str, Any] | None]:
        row = await self._load(sid)
        by_name = {t.spec.name: t for t in tools}
        tool = by_name.get(call.name)

        def reply(text: str, error: bool = False) -> ChatMessage:
            return ChatMessage(
                role="tool", tool_call_id=call.id, tool_name=call.name, text=text, is_error=error
            )

        if tool is None:
            await self._emit(
                sid,
                "rejected_call",
                {
                    "tool": call.name,
                    "arguments": call.arguments,
                    "rule": "unknown_tool",
                    "message": f"There is no tool named {call.name}.",
                    "spec_ref": None,
                },
            )
            return reply(json.dumps({"rejected": {"rule": "unknown_tool"}}), True), None
        if tool.agent_id is None:
            target = by_name.get(str(call.arguments.get("agent", "")))
            task_id = str(call.arguments.get("task_id", ""))
            await self._emit(sid, "tool_call", {"tool": call.name, "arguments": call.arguments})
            if target is None or target.agent_id is None or not task_id:
                message = "Give agent (an agent tool name) and task_id."
                await self._emit(
                    sid,
                    "rejected_call",
                    {
                        "tool": call.name,
                        "arguments": call.arguments,
                        "rule": "bad_arguments",
                        "message": message,
                        "spec_ref": None,
                    },
                )
                return reply(json.dumps({"rejected": {"message": message}}), True), None
            if not SessionIds(row.ids).task_known(target.agent_id, task_id):
                message = (
                    f"task_id '{task_id}' was never returned by this agent; only tasks it "
                    "returned can be read or canceled."
                )
                spec_ref = "A2A §3.4.2 (task ids are server-generated)"
                await self._emit(
                    sid,
                    "rejected_call",
                    {
                        "tool": call.name,
                        "agent_id": target.agent_id,
                        "arguments": call.arguments,
                        "rule": "task_unknown",
                        "message": message,
                        "spec_ref": spec_ref,
                    },
                )
                body = {
                    "rejected": {"rule": "task_unknown", "message": message, "spec_ref": spec_ref}
                }
                return reply(json.dumps(body), True), None
            if call.name == "get_task":
                result = await self._executor.get_task(target.agent_id, task_id)
            else:
                result = await self._executor.cancel_task(target.agent_id, task_id)
            await self._record(sid, target.agent_id, result)
            await self._emit(
                sid,
                "tool_result",
                {
                    **result.model_dump(mode="json"),
                    "agent_id": target.agent_id,
                    "tool": call.name,
                    "shown_to_user": False,
                },
            )
            return reply(result.for_llm(False)), self._decide(
                row, target.agent_id, call.name, result
            )

        agent = await self._wb.agents.get(tool.agent_id)
        await self._emit(
            sid,
            "tool_call",
            {
                "tool": call.name,
                "agent_id": agent.id,
                "agent": agent.name,
                "arguments": call.arguments,
            },
        )
        ids = SessionIds(row.ids)
        try:
            validate_call(card_from_json(agent.card), agent.id, call.arguments, ids)
        except CallRejected as exc:
            await self._emit(
                sid,
                "rejected_call",
                {
                    "tool": call.name,
                    "agent_id": agent.id,
                    "agent": agent.name,
                    "arguments": call.arguments,
                    "rule": exc.rule,
                    "message": exc.message,
                    "spec_ref": exc.spec_ref,
                },
            )
            body = {
                "rejected": {"rule": exc.rule, "message": exc.message, "spec_ref": exc.spec_ref}
            }
            return reply(json.dumps(body), True), None
        context_id = call.arguments.get("context_id")
        task_id = call.arguments.get("task_id")
        if task_id and not context_id:
            context_id = ids.context_of(agent.id, task_id)
        conversation_id = (
            (row.contexts or {}).get(agent.id, {}).get(context_id) if context_id else None
        )
        answered_by = (
            "assistant"
            if task_id and ids.task_state(agent.id, task_id) == "input_required"
            else None
        )
        result = await self._execute(sid, row, agent.id, call.arguments, conversation_id, limits)
        shown = row.response_mode == "pass_through"
        await self._emit(
            sid,
            "tool_result",
            {
                **result.model_dump(mode="json"),
                "agent_id": agent.id,
                "tool": call.name,
                "answered_by": answered_by,
                "shown_to_user": shown,
            },
        )
        return reply(result.for_llm(shown)), self._decide(row, agent.id, call.name, result)

    async def _direct_reply(self, sid: str, text: str) -> bool:
        """Send the user's answer straight to the waiting agent; return False if paused again."""
        row = await self._load(sid)
        pending = row.pending or {}
        args = {"message": text}
        if pending.get("task_id"):
            args["task_id"] = pending["task_id"]
        if pending.get("context_id"):
            args["context_id"] = pending["context_id"]
        await self._save(sid, pending=None)
        result = await self._execute(
            sid,
            row,
            pending["agent_id"],
            args,
            pending.get("conversation_id"),
            Limits(**row.limits),
        )
        await self._emit(
            sid,
            "tool_result",
            {
                **result.model_dump(mode="json"),
                "agent_id": pending["agent_id"],
                "tool": pending.get("tool"),
                "answered_by": "user",
                "shown_to_user": True,
            },
        )
        await self._append(
            sid,
            ChatMessage(
                role="user",
                text=f"[The user answered {result.agent} directly: {text!r}]"
                f"{RESULT_MARKER}{result.for_llm(True)}",
            ),
        )
        pause = self._decide(row, pending["agent_id"], pending.get("tool") or "", result)
        if pause:
            await self._pause(sid, pause)
            return False
        return True

    async def _resume(self, sid: str) -> None:
        row = await self._load(sid)
        pending = row.pending
        if row.status != "awaiting_sign_in" or not pending:
            return
        watcher = self._watchers.pop(sid, None)
        if watcher and watcher is not asyncio.current_task():
            watcher.cancel()
        await self._save(sid, status="running", pending=None)
        await self._emit(
            sid, "resumed", {"agent": pending.get("agent"), "task_id": pending.get("task_id")}
        )
        if pending.get("task_id"):
            result = await self._executor.get_task(pending["agent_id"], pending["task_id"])
            await self._record(sid, pending["agent_id"], result)
            await self._emit(
                sid,
                "tool_result",
                {
                    **result.model_dump(mode="json"),
                    "agent_id": pending["agent_id"],
                    "tool": "get_task",
                    "shown_to_user": False,
                },
            )
            note = (
                f"[The user signed in for {result.agent}. Current state of task "
                f"{pending['task_id']}:]{RESULT_MARKER}{result.for_llm(False)}"
            )
        else:
            note = f"[The user signed in for {pending.get('agent')}.]"
        await self._append(sid, ChatMessage(role="user", text=note))
        await self._loop(sid)

    async def _watch(self, sid: str, pause: dict[str, Any]) -> None:
        """Poll the paused task with GetTask (A2A §7.6.2) and resume when its state changes."""
        row = await self._load(sid)
        deadline = time.monotonic() + Limits(**row.limits).run_timeout_s
        if not pause.get("task_id"):
            return
        while time.monotonic() < deadline:
            await asyncio.sleep(self._watch_interval)
            row = await self._load(sid)
            if row.status != "awaiting_sign_in":
                return
            result = await self._executor.get_task(pause["agent_id"], pause["task_id"])
            if result.state and result.state != "auth_required":
                try:
                    steps = self.resume(sid)
                except TurnInProgressError:
                    continue
                self._watchers.pop(sid, None)
                async for _ in steps:
                    pass
                return
