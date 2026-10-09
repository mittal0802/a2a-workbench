"""Assistant chats and LLM provider keys."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.api.routes_conversations import _spawn
from a2a_workbench.core.assistant.keys import ProviderKeyInfo
from a2a_workbench.core.assistant.service import ResponseMode, SessionIn, SessionOut
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api/assistant")


class KeyIn(BaseModel):
    api_key: str
    base_url: str | None = None


class MessageIn(BaseModel):
    text: str


class SessionPatch(BaseModel):
    response_mode: ResponseMode | None = None
    agent_ids: list[str] | None = None
    title: str | None = None


def _bad(exc: ValueError) -> HTTPException:
    return HTTPException(422, detail={"category": "workbench", "message": str(exc)})


@router.get("/providers")
async def list_providers(wb: Workbench = Depends(get_workbench)) -> list[ProviderKeyInfo]:
    return await wb.provider_keys.list()


@router.put("/providers/{provider}")
async def put_provider(
    provider: str, body: KeyIn, wb: Workbench = Depends(get_workbench)
) -> ProviderKeyInfo:
    try:
        return await wb.provider_keys.put(provider, body.api_key, body.base_url)
    except ValueError as exc:
        raise _bad(exc) from None


@router.delete("/providers/{provider}", status_code=204)
async def delete_provider(provider: str, wb: Workbench = Depends(get_workbench)) -> Response:
    try:
        await wb.provider_keys.delete(provider)
    except ValueError as exc:
        raise _bad(exc) from None
    return Response(status_code=204)


@router.get("/sessions")
async def list_sessions(wb: Workbench = Depends(get_workbench)) -> list[SessionOut]:
    return await wb.assistant.list()


@router.post("/sessions", status_code=201)
async def create_session(body: SessionIn, wb: Workbench = Depends(get_workbench)) -> SessionOut:
    try:
        return await wb.assistant.create(body)
    except ValueError as exc:
        raise _bad(exc) from None


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str, after_seq: int = 0, wb: Workbench = Depends(get_workbench)
) -> dict[str, Any]:
    # Steps first: a turn saves its status before emitting steps, so the session read
    # afterwards is never older than the steps returned.
    steps = await wb.assistant.steps(session_id, after_seq)
    session = await wb.assistant.get(session_id)
    return {
        "session": session.model_dump(mode="json"),
        "steps": [s.model_dump(mode="json") for s in steps],
    }


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str, body: SessionPatch, wb: Workbench = Depends(get_workbench)
) -> SessionOut:
    try:
        return await wb.assistant.update(
            session_id,
            response_mode=body.response_mode,
            agent_ids=body.agent_ids,
            title=body.title,
        )
    except ValueError as exc:
        raise _bad(exc) from None


@router.post("/sessions/{session_id}/messages", status_code=202)
async def send(
    session_id: str, body: MessageIn, request: Request, wb: Workbench = Depends(get_workbench)
) -> dict[str, bool]:
    await wb.assistant.get(session_id)
    _spawn(request, wb.assistant.send(session_id, body.text))
    return {"accepted": True}


@router.post("/sessions/{session_id}/resume", status_code=202)
async def resume(
    session_id: str, request: Request, wb: Workbench = Depends(get_workbench)
) -> dict[str, bool]:
    await wb.assistant.get(session_id)
    _spawn(request, wb.assistant.resume(session_id))
    return {"accepted": True}


@router.post("/sessions/{session_id}/stop", status_code=204)
async def stop(session_id: str, wb: Workbench = Depends(get_workbench)) -> Response:
    await wb.assistant.stop(session_id)
    return Response(status_code=204)
