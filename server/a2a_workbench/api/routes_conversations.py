"""Conversation endpoints; sends run as background tasks and stream over /ws."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import PartInput
from a2a_workbench.core.conversations.service import ConversationOut
from a2a_workbench.core.faults.profile import FaultProfile
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api")


class ConversationIn(BaseModel):
    agent_id: str
    title: str | None = None


class MessageIn(BaseModel):
    parts: list[PartInput] = Field(min_length=1)
    options: SendOptions = Field(default_factory=SendOptions)


def _spawn(request: Request, events: AsyncIterator[Any]) -> None:
    async def drain() -> None:
        async for _ in events:
            pass

    tasks: set[asyncio.Task[None]] = request.app.state.tasks
    task = asyncio.create_task(drain())
    tasks.add(task)
    task.add_done_callback(tasks.discard)


@router.get("/agents/{agent_id}/conversations")
async def list_conversations(
    agent_id: str, wb: Workbench = Depends(get_workbench)
) -> list[ConversationOut]:
    await wb.agents.get(agent_id)
    return await wb.conversations.list_for_agent(agent_id)


@router.post("/conversations", status_code=201)
async def create_conversation(
    body: ConversationIn, wb: Workbench = Depends(get_workbench)
) -> ConversationOut:
    await wb.agents.get(body.agent_id)
    return await wb.conversations.create(body.agent_id, title=body.title)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str, wb: Workbench = Depends(get_workbench)
) -> dict[str, Any]:
    conv = await wb.conversations.get(conversation_id)
    events = await wb.conversations.events(conversation_id)
    return {
        "conversation": conv.model_dump(mode="json"),
        "events": [e.model_dump(mode="json") for e in events],
    }


@router.post("/conversations/{conversation_id}/messages", status_code=202)
async def send_message(
    conversation_id: str, body: MessageIn, request: Request, wb: Workbench = Depends(get_workbench)
) -> dict[str, bool]:
    await wb.conversations.get(conversation_id)
    _spawn(request, wb.conversations.send(conversation_id, body.parts, body.options))
    return {"accepted": True}


class ResubscribeIn(BaseModel):
    force: bool = False
    faults: FaultProfile | None = None


@router.post("/conversations/{conversation_id}/resubscribe", status_code=202)
async def resubscribe(
    conversation_id: str,
    request: Request,
    body: ResubscribeIn | None = None,
    wb: Workbench = Depends(get_workbench),
) -> dict[str, bool]:
    await wb.conversations.get(conversation_id)
    body = body or ResubscribeIn()
    _spawn(
        request,
        wb.conversations.resubscribe(conversation_id, faults=body.faults, force=body.force),
    )
    return {"accepted": True}


@router.post("/conversations/{conversation_id}/check-status", status_code=202)
async def check_status(
    conversation_id: str, request: Request, wb: Workbench = Depends(get_workbench)
) -> dict[str, bool]:
    await wb.conversations.get(conversation_id)
    _spawn(request, wb.conversations.check_status(conversation_id))
    return {"accepted": True}


@router.post("/conversations/{conversation_id}/cancel", status_code=202)
async def cancel(
    conversation_id: str, request: Request, wb: Workbench = Depends(get_workbench)
) -> dict[str, bool]:
    await wb.conversations.get(conversation_id)
    _spawn(request, wb.conversations.cancel(conversation_id))
    return {"accepted": True}


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str, wb: Workbench = Depends(get_workbench)
) -> Response:
    await wb.conversations.delete(conversation_id)
    return Response(status_code=204)
