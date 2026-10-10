"""Deliberate A2A violations for the zoo, so each health check can be shown to detect one.

A break is a name; ``BREAKS`` lists them with the rule each violates. Card
breaks change the Agent Card; handler breaks are a subclass of the SDK's own
request handler that bends one behaviour; executor breaks change what the zoo
agent does.
"""

import asyncio
import inspect
from collections.abc import AsyncGenerator
from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers.default_request_handler_v2 import DefaultRequestHandlerV2
from a2a.server.tasks import BasePushNotificationSender
from a2a.types import (
    AgentCard,
    AgentInterface,
    CancelTaskRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.errors import InvalidParamsError, TaskNotFoundError

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
    "get-unknown-returns": "GetTask invents a task for an unknown id (A2A §3.1.3)",
    "get-history-ignored": "GetTask ignores historyLength (A2A §3.2.4)",
    "list-ignores-context": "ListTasks ignores the contextId filter (A2A §3.1.4)",
    "list-artifacts": "ListTasks includes artifacts without includeArtifacts (A2A §3.1.4)",
    "list-order": "ListTasks oldest first (A2A §3.1.4)",
    "cancel-terminal-ok": "canceling a finished task succeeds (A2A §3.1.5)",
    "cancel-unknown-ok": "CancelTask invents a task for an unknown id (A2A §3.1.5)",
    "stream-status-first": "a stream that starts with a status update (A2A §3.1.2)",
    "stream-no-close": "a stream left open after the task finished (A2A §3.1.2)",
    "subscribe-no-task-first": "SubscribeToTask without the Task first (A2A §3.1.6)",
    "subscribe-terminal-ok": "SubscribeToTask streams a finished task (A2A §3.1.6)",
    "streaming-undeclared-works": "streams although capabilities.streaming is false (A2A §3.3.4)",
    "push-undeclared-works": "push configs accepted though not declared (A2A §3.3.4)",
    "push-delete-not-idempotent": "deleting a deleted push config fails (A2A §3.1.10)",
    "push-no-auth": "push notifications sent without Authorization (A2A §4.3.3)",
    "auth-not-enforced": "declares Bearer auth but serves anyone (A2A §7.4)",
    "no-challenge": "401 without WWW-Authenticate (A2A §3.3.2)",
    "extension-not-enforced": "a required extension is not enforced (A2A §3.3.4)",
    "wrong-error-codes": "InvalidParams instead of TaskNotFound / TaskNotCancelable (A2A §5.4)",
    "cancel-on-disconnect": "cancels a task when its stream drops (A2A §3.5.2)",
    "single-subscriber": "a second stream for a task closes after the Task (A2A §3.5.2)",
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
        self._subscribers: dict[str, int] = {}
        self._background: set[asyncio.Task[Any]] = set()

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

    async def on_get_task(self, params: GetTaskRequest, context: ServerCallContext) -> Task:
        """GetTask, inventing tasks, ignoring historyLength or erring wrongly as configured."""
        if "get-history-ignored" in self.breaks:
            params.ClearField("history_length")
        try:
            return await super().on_get_task(params, context)
        except TaskNotFoundError:
            if "get-unknown-returns" in self.breaks:
                return _invented(params.id, TaskState.TASK_STATE_COMPLETED)
            if "wrong-error-codes" in self.breaks:
                raise InvalidParamsError(message="no such task") from None
            raise

    async def on_list_tasks(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> ListTasksResponse:
        """ListTasks, ignoring filters, leaking artifacts or reversing order as configured."""
        if "list-ignores-context" in self.breaks:
            params.ClearField("context_id")
        if "list-artifacts" in self.breaks:
            params.include_artifacts = True
        page = await super().on_list_tasks(params, context)
        if "list-order" in self.breaks:
            tasks = list(page.tasks)[::-1]
            del page.tasks[:]
            page.tasks.extend(tasks)
        return page

    async def on_cancel_task(self, params: CancelTaskRequest, context: ServerCallContext) -> Task:
        """CancelTask, accepting finished or unknown tasks as configured."""
        task = await self.task_store.get(params.id, context)
        if task is None and "cancel-unknown-ok" in self.breaks:
            return _invented(params.id, TaskState.TASK_STATE_CANCELED)
        if (
            task is not None
            and task.status.state in TERMINAL
            and "cancel-terminal-ok" in self.breaks
        ):
            return task
        if (
            task is not None
            and task.status.state in TERMINAL
            and "wrong-error-codes" in self.breaks
        ):
            raise InvalidParamsError(message="task is finished")
        return await super().on_cancel_task(params, context)

    async def on_create_task_push_notification_config(
        self, params: Any, context: ServerCallContext
    ) -> Any:
        """Create a push config, ignoring the push capability as configured."""
        if "push-undeclared-works" in self.breaks:
            unchecked = inspect.unwrap(
                DefaultRequestHandlerV2.on_create_task_push_notification_config
            )
            return await unchecked(self, params, context)
        return await super().on_create_task_push_notification_config(params, context)

    async def on_delete_task_push_notification_config(
        self, params: Any, context: ServerCallContext
    ) -> Any:
        """Delete a push config, failing when it is already gone as configured."""
        if "push-delete-not-idempotent" in self.breaks:
            listed = await self.on_list_task_push_notification_configs(
                ListTaskPushNotificationConfigsRequest(task_id=params.task_id), context
            )
            if params.id not in {c.id for c in listed.configs}:
                raise TaskNotFoundError(message="no such push notification config")
        return await super().on_delete_task_push_notification_config(params, context)

    async def on_message_send_stream(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[Any, None]:
        """Stream, starting with a status update or staying open as configured."""
        first = True
        source = (
            inspect.unwrap(DefaultRequestHandlerV2.on_message_send_stream)(self, params, context)
            if "streaming-undeclared-works" in self.breaks
            else super().on_message_send_stream(params, context)
        )
        task_id = None
        finished = False
        try:
            async for event in source:
                if isinstance(event, Task):
                    task_id = event.id
                if first and isinstance(event, Task) and "stream-status-first" in self.breaks:
                    yield TaskStatusUpdateEvent(
                        task_id=event.id, context_id=event.context_id, status=event.status
                    )
                first = False
                finished = finished or _terminal_event(event) or _interrupted_event(event)
                yield event
                if "stream-no-close" in self.breaks and _terminal_event(event):
                    await asyncio.sleep(20)
        finally:
            if task_id and not finished and "cancel-on-disconnect" in self.breaks:
                job = asyncio.create_task(
                    self.on_cancel_task(CancelTaskRequest(id=task_id), context)
                )
                self._background.add(job)
                job.add_done_callback(self._background.discard)

    async def on_subscribe_to_task(
        self, params: SubscribeToTaskRequest, context: ServerCallContext
    ) -> AsyncGenerator[Any, None]:
        """Subscribe, dropping the first Task or streaming finished tasks as configured."""
        task = await self.task_store.get(params.id, context)
        if (
            task is not None
            and task.status.state in TERMINAL
            and "subscribe-terminal-ok" in self.breaks
        ):
            yield task
            return
        first = True
        self._subscribers[params.id] = self._subscribers.get(params.id, 0) + 1
        crowded = self._subscribers[params.id] > 1 and "single-subscriber" in self.breaks
        try:
            async for event in super().on_subscribe_to_task(params, context):
                if first and isinstance(event, Task) and "subscribe-no-task-first" in self.breaks:
                    first = False
                    continue
                first = False
                yield event
                if crowded:
                    return
        finally:
            self._subscribers[params.id] -= 1


def _invented(task_id: str, state: Any) -> Task:
    return Task(id=task_id, context_id="invented", status=TaskStatus(state=state))


def _interrupted_event(event: Any) -> bool:
    status = getattr(event, "status", None)
    return status is not None and status.state in (
        TaskState.TASK_STATE_INPUT_REQUIRED,
        TaskState.TASK_STATE_AUTH_REQUIRED,
    )


def _terminal_event(event: Any) -> bool:
    status = getattr(event, "status", None)
    return status is not None and status.state in TERMINAL


class BrokenPushSender(BasePushNotificationSender):
    """The SDK push sender, sending without the config's Authorization (``push-no-auth``)."""

    async def _dispatch_notification(self, event: Any, push_info: Any, task_id: str) -> bool:
        stripped = type(push_info)()
        stripped.CopyFrom(push_info)
        stripped.ClearField("authentication")
        return await super()._dispatch_notification(event, stripped, task_id)
