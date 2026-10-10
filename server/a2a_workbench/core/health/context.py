"""What a check can use while it probes an agent."""

from collections.abc import Awaitable, Callable
from typing import Any

from a2a.types import AgentCard
from pydantic import BaseModel

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import AnyPartInput, TextPartInput
from a2a_workbench.core.conversations.timeline import TimelineEvent
from a2a_workbench.core.registry.service import AgentOut

PROBE_TIMEOUT_S = 60.0


class RunContext:
    """The agent under test, the interface being tested, and helpers that record evidence.

    Every helper goes through the Workbench services (and so the official
    SDK); exchanges they cause are collected as the current check's evidence.
    ``created_tasks`` holds every task the run created, so destructive probes
    can stay within them.
    """

    def __init__(
        self,
        wb: Any,
        agent: AgentOut,
        card: AgentCard,
        *,
        interface_url: str | None,
        binding: str | None,
        conversation_id: str,
        faults: Any = None,
    ) -> None:
        self.wb = wb
        self.agent = agent
        self.card = card
        self.interface_url = interface_url
        self.binding = binding
        self.conversation_id = conversation_id
        self.faults = faults
        self.created_tasks: list[str] = []
        self.cache: dict[str, Any] = {}

    @property
    def capabilities(self) -> Any:
        """The card's capabilities."""
        return self.card.capabilities

    async def cached(self, key: str, make: Callable[[], Awaitable[Any]]) -> Any:
        """Return ``make()``'s result, computed once per run and interface.

        The exchanges recorded while computing it are attributed to every
        check that reuses it, so each keeps its evidence.
        """
        from a2a_workbench.core.connection.recorder import (
            add_to_current_scope,
            current_exchange_ids,
        )

        if key in self.cache:
            value, ids = self.cache[key]
            add_to_current_scope(ids)
            return value
        before = set(current_exchange_ids())
        value = await make()
        ids = [i for i in current_exchange_ids() if i not in before]
        self.cache[key] = (value, ids)
        return value

    async def new_conversation(self) -> str:
        """Start a fresh probe conversation (origin ``health``)."""
        conv = await self.wb.conversations.create(
            self.agent.id, title="Health check probe", origin="health"
        )
        return conv.id

    def probe_texts(self) -> list[str]:
        """Messages to probe with: the card's skill examples, else a greeting."""
        texts = [ex for skill in self.card.skills for ex in skill.examples]
        return texts or ["hello"]

    async def reply(self, text: str | None = None, **kw: Any) -> "Reply":
        """Send ``text`` (default: the first probe text) and return the folded reply."""
        return fold(await self.send(text or self.probe_texts()[0], **kw))

    async def open_task(self) -> "Reply | None":
        """A task left waiting for input, found by trying up to three probe texts."""

        async def find() -> "Reply | None":
            for text in self.probe_texts()[:3]:
                r = await self.reply(text)
                if r.kind == "task" and r.state in INTERRUPTED_STATES:
                    return r
            return None

        return await self.cached("open_task", find)

    async def send(
        self,
        text: str,
        *,
        options: SendOptions | None = None,
        conversation_id: str | None = None,
        parts: list[AnyPartInput] | None = None,
    ) -> list[TimelineEvent]:
        """Send a message through ``ConversationService`` and return its events.

        Defaults to a blocking, non-streaming send with exactly the given ids.
        The run's fault profile applies unless ``options`` sets its own.
        Tasks the agent creates are added to ``created_tasks``.
        """
        opts = options or SendOptions(stream=False, inherit_ids=False)
        if self.faults is not None and opts.faults is None:
            opts = opts.model_copy(update={"faults": self.faults})
        conv = conversation_id or await self.new_conversation()
        events = [
            e
            async for e in self.wb.conversations.send(
                conv, parts or [TextPartInput(text=text)], opts
            )
        ]
        for e in events:
            if (
                e.task_id
                and e.kind in ("task", "status", "artifact")
                and e.task_id not in self.created_tasks
            ):
                self.created_tasks.append(e.task_id)
        return events


class Reply(BaseModel):
    """What one send produced, folded from its timeline events."""

    kind: str  # "task" | "message" | "error" | "none"
    task_id: str | None = None
    context_id: str | None = None
    state: str | None = None
    task: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    artifacts: int = 0
    messages: int = 0
    first_event: str | None = None
    events: int = 0


TERMINAL_STATES = frozenset({"completed", "failed", "canceled", "rejected"})
INTERRUPTED_STATES = frozenset({"input_required", "auth_required"})


def fold(events: list[TimelineEvent]) -> Reply:
    """Summarize a send's timeline events (user_message excluded)."""
    agent = [e for e in events if e.kind != "user_message"]
    reply = Reply(kind="none", events=len(agent))
    if agent:
        reply.first_event = agent[0].kind
    for e in agent:
        if e.kind in ("task", "status", "artifact"):
            reply.kind = "task"
            reply.task_id = e.task_id or reply.task_id
            reply.context_id = e.context_id or reply.context_id
            reply.state = e.data.get("state", reply.state)
            if e.kind == "task":
                reply.task = e.data.get("task")
                reply.artifacts = max(
                    reply.artifacts, len((reply.task or {}).get("artifacts") or [])
                )
            if e.kind == "artifact":
                reply.artifacts = max(reply.artifacts, 1)
            status = e.data.get("status") or (e.data.get("task") or {}).get("status") or {}
            if status.get("message"):
                reply.messages += 1
        elif e.kind == "message":
            if reply.kind == "none":
                reply.kind = "message"
            reply.context_id = e.context_id or reply.context_id
            reply.messages += 1
        elif e.kind in ("error", "connection_lost"):
            reply.error = dict(e.data)
            if reply.kind == "none":
                reply.kind = "error"
    return reply
