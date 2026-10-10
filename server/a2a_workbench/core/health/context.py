"""What a check can use while it probes an agent."""

from typing import Any

from a2a.types import AgentCard

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

    async def new_conversation(self) -> str:
        """Start a fresh probe conversation (origin ``health``)."""
        conv = await self.wb.conversations.create(
            self.agent.id, title="Health check probe", origin="health"
        )
        return conv.id

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
        Tasks the agent creates are added to ``created_tasks``.
        """
        opts = options or SendOptions(stream=False, inherit_ids=False)
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
