"""Deliberate A2A violations for the zoo, so each health check can be shown to detect one.

A break is a name; ``BREAKS`` lists them with the rule each violates. Card
breaks change the Agent Card; handler breaks are a subclass of the SDK's own
request handler that bends one behaviour; executor breaks change what the zoo
agent does.
"""

from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.types import AgentCard, AgentInterface, Message, SendMessageRequest, Task, TaskState

TERMINAL = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_REJECTED,
}

BREAKS: dict[str, str] = {
    "card-missing-fields": "defaultOutputModes left empty (REQUIRED)",
    "card-no-version": "an interface without protocolVersion (A2A §8.3.1)",
    "skill-no-tags": "a skill without its REQUIRED tags",
    "card-no-cache": "card served without Cache-Control (A2A §8.6.1)",
    "bad-signature": "card changed after signing (A2A §8.4.3)",
    "extended-ignores-capability": "extended card served though not declared (A2A §3.3.4)",
    "dead-interface": "an interface that does not answer (A2A §5.2)",
    "split-stores": "REST does not see tasks made over JSON-RPC (A2A §5.1)",
    "no-context": "responses without contextId (A2A §3.4.1)",
    "unknown-task-ok": "unknown taskId starts a new task instead of TaskNotFoundError (A2A §3.4.2)",
    "mismatch-ok": "mismatching contextId and taskId accepted (A2A §3.4.3)",
    "terminal-accepts": "a terminal task accepts a new message (A2A §3.1.1)",
    "history-ignored": "historyLength is ignored (A2A §3.2.4)",
    "blocking-working": "blocking sends return before the task settles (A2A §3.2.2)",
    "message-output": "results returned only in messages (A2A §3.7)",
}


def apply_card_breaks(card: AgentCard, breaks: frozenset[str], base_url: str) -> None:
    """Change ``card`` in place for the card breaks in ``breaks`` (before signing)."""
    if "card-missing-fields" in breaks:
        del card.default_output_modes[:]
    if "card-no-version" in breaks and card.supported_interfaces:
        card.supported_interfaces[0].protocol_version = ""
    if "skill-no-tags" in breaks and card.skills:
        del card.skills[0].tags[:]
    if "extended-ignores-capability" in breaks:
        card.capabilities.extended_agent_card = False
    if "dead-interface" in breaks:
        card.supported_interfaces.append(
            AgentInterface(
                url=f"{base_url}/dead", protocol_binding="HTTP+JSON", protocol_version="1.0"
            )
        )


def tamper_signed_card(card: AgentCard, breaks: frozenset[str]) -> None:
    """Change a signed card so its signature no longer verifies (``bad-signature``)."""
    if "bad-signature" in breaks:
        card.description = card.description + " (changed after signing)"


class BrokenHandler(DefaultRequestHandlerV2):
    """The SDK request handler with the handler breaks in ``breaks`` applied."""

    def __init__(self, *args: Any, breaks: frozenset[str] = frozenset(), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.breaks = breaks

    async def on_message_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Message | Task:
        """Send, bending task-id, context, history and blocking rules as configured."""
        message = params.message
        if message.task_id:
            task = await self.task_store.get(message.task_id, context)
            if task is None and "unknown-task-ok" in self.breaks:
                message.task_id = ""
            elif (
                task is not None
                and task.status.state in TERMINAL
                and "terminal-accepts" in self.breaks
            ):
                message.task_id = ""
            elif task is not None and "mismatch-ok" in self.breaks and message.context_id:
                message.context_id = task.context_id
        if "history-ignored" in self.breaks:
            params.configuration.ClearField("history_length")
        if "blocking-working" in self.breaks:
            params.configuration.return_immediately = True
        result = await super().on_message_send(params, context)
        if "no-context" in self.breaks:
            result.context_id = ""
        return result

    async def on_get_extended_agent_card(
        self, params: Any, context: ServerCallContext
    ) -> AgentCard:
        """Serve the extended card even when the capability is not declared, if configured to."""
        if "extended-ignores-capability" in self.breaks:
            return self.extended_agent_card or self._agent_card
        return await super().on_get_extended_agent_card(params, context)
