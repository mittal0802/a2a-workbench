"""Task operations on an agent: get, list, cancel and subscribe."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from a2a.client import Client
from a2a.types import (
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    SubscribeToTaskRequest,
    TaskState,
)
from pydantic import BaseModel, Field

from a2a_workbench.core.a2a_json import card_from_json, state_name, to_json
from a2a_workbench.core.connection.client import open_client, select_interface
from a2a_workbench.core.connection.recorder import ExchangeSink, recording_scope
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.faults.profile import FaultProfile
from a2a_workbench.core.registry.service import AgentService

_PAYLOAD_KIND = {
    "task": "task",
    "message": "message",
    "status_update": "status_update",
    "artifact_update": "artifact_update",
}


class ListTasksFilter(BaseModel):
    """Every ListTasks parameter; ``status`` is a short state name like ``completed``."""

    context_id: str | None = None
    status: str | None = None
    status_timestamp_after: datetime | None = None
    include_artifacts: bool | None = None
    history_length: int | None = Field(default=None, ge=0)
    page_size: int | None = Field(default=None, ge=1)
    page_token: str | None = None


def _task_json(task: Any) -> dict[str, Any]:
    out = to_json(task)
    out["state"] = state_name(task.status.state)
    return out


def _list_request(f: ListTasksFilter) -> ListTasksRequest:
    req = ListTasksRequest()
    if f.context_id:
        req.context_id = f.context_id
    if f.status:
        req.status = TaskState.Value(f"TASK_STATE_{f.status.upper()}")
    if f.status_timestamp_after is not None:
        req.status_timestamp_after.FromDatetime(f.status_timestamp_after)
    if f.include_artifacts is not None:
        req.include_artifacts = f.include_artifacts
    if f.history_length is not None:
        req.history_length = f.history_length
    if f.page_size is not None:
        req.page_size = f.page_size
    if f.page_token:
        req.page_token = f.page_token
    return req


class TaskService:
    """Calls the A2A task methods on a registered agent's selected interface.

    Every call is recorded under its operation label (``get_task``,
    ``list_tasks``, ``cancel_task``, ``subscribe_task``) and accepts an optional
    fault profile. Failures raise ``AgentCallError``.
    """

    def __init__(self, agents: AgentService, sink: ExchangeSink) -> None:
        self._agents = agents
        self._sink = sink

    @asynccontextmanager
    async def _client(
        self, agent_id: str, operation: str, faults: FaultProfile | None, *, streaming: bool = False
    ) -> AsyncIterator[Client]:
        agent = await self._agents.row(agent_id)
        card = card_from_json(agent.card)
        with recording_scope(operation, agent_id=agent_id):
            try:
                iface = select_interface(card, agent.selected_interface_url)
                client = await open_client(
                    card, iface, self._sink, streaming=streaming, faults=faults
                )
                async with client:
                    yield client
            except AgentCallError:
                raise
            except Exception as exc:
                raise AgentCallError(classify_error(exc)) from exc

    async def get(
        self,
        agent_id: str,
        task_id: str,
        *,
        history_length: int | None = None,
        faults: FaultProfile | None = None,
    ) -> dict[str, Any]:
        """Return the task's JSON plus its short ``state``."""
        req = GetTaskRequest(id=task_id)
        if history_length is not None:
            req.history_length = history_length
        async with self._client(agent_id, "get_task", faults) as client:
            return _task_json(await client.get_task(req))

    async def list(
        self, agent_id: str, f: ListTasksFilter, *, faults: FaultProfile | None = None
    ) -> dict[str, Any]:
        """Return ``{"tasks", "next_page_token", "page_size", "total_size"}`` for ``f``."""
        async with self._client(agent_id, "list_tasks", faults) as client:
            resp = await client.list_tasks(_list_request(f))
        return {
            "tasks": [_task_json(t) for t in resp.tasks],
            "next_page_token": resp.next_page_token or None,
            "page_size": resp.page_size,
            "total_size": resp.total_size,
        }

    async def cancel(
        self,
        agent_id: str,
        task_id: str,
        *,
        metadata: dict[str, Any] | None = None,
        faults: FaultProfile | None = None,
    ) -> dict[str, Any]:
        """Request cancellation and return the resulting task."""
        req = CancelTaskRequest(id=task_id)
        if metadata:
            req.metadata.update(metadata)
        async with self._client(agent_id, "cancel_task", faults) as client:
            return _task_json(await client.cancel_task(req))

    async def subscribe(
        self, agent_id: str, task_id: str, *, faults: FaultProfile | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield ``{"kind", "state", "event"}`` for each event of the resubscribed stream."""
        async with self._client(agent_id, "subscribe_task", faults, streaming=True) as client:
            async for resp in client.subscribe(SubscribeToTaskRequest(id=task_id)):
                payload = resp.WhichOneof("payload")
                message = getattr(resp, payload)
                state = None
                if payload == "task":
                    state = state_name(message.status.state)
                elif payload == "status_update":
                    state = state_name(message.status.state)
                yield {"kind": _PAYLOAD_KIND[payload], "state": state, "event": to_json(message)}
