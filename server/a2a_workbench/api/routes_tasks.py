"""Task endpoints."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.tasks.service import ListTasksFilter
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api/agents/{agent_id}/tasks")


class CancelIn(BaseModel):
    metadata: dict[str, Any] | None = None


@router.get("")
async def list_tasks(
    agent_id: str,
    f: Annotated[ListTasksFilter, Query()],
    wb: Workbench = Depends(get_workbench),
) -> dict[str, Any]:
    return await wb.tasks.list(agent_id, f)


@router.get("/{task_id}")
async def get_task(
    agent_id: str,
    task_id: str,
    history_length: int | None = None,
    wb: Workbench = Depends(get_workbench),
) -> dict[str, Any]:
    return await wb.tasks.get(agent_id, task_id, history_length=history_length)


@router.post("/{task_id}/cancel")
async def cancel_task(
    agent_id: str, task_id: str, body: CancelIn, wb: Workbench = Depends(get_workbench)
) -> dict[str, Any]:
    return await wb.tasks.cancel(agent_id, task_id, metadata=body.metadata)


@router.post("/{task_id}/watch")
async def watch_task(
    agent_id: str, task_id: str, request: Request, wb: Workbench = Depends(get_workbench)
) -> dict[str, str]:
    """Attach the task to a conversation and resubscribe to it there."""
    task = await wb.tasks.get(agent_id, task_id, history_length=0)
    conv = await wb.conversations.for_task(
        agent_id, task_id, context_id=task.get("contextId"), state=task["state"]
    )

    async def drain() -> None:
        async for _ in wb.conversations.resubscribe(conv.id):
            pass

    tasks: set[asyncio.Task[None]] = request.app.state.tasks
    job = asyncio.create_task(drain())
    tasks.add(job)
    job.add_done_callback(tasks.discard)
    return {"conversation_id": conv.id}
