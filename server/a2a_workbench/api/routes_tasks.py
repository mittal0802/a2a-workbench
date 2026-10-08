"""Task endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
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
