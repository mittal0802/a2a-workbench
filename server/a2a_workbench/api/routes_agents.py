"""Agent registry endpoints."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.registry.service import AgentOut, CardPreview, ExtendedCardOut
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api")


class UrlIn(BaseModel):
    url: str
    card_path: str | None = None


class AgentPatch(BaseModel):
    selected_interface_url: str


@router.post("/cards/preview")
async def preview_card(body: UrlIn, wb: Workbench = Depends(get_workbench)) -> CardPreview:
    return await wb.agents.preview(body.url)


@router.get("/agents")
async def list_agents(wb: Workbench = Depends(get_workbench)) -> list[AgentOut]:
    return await wb.agents.list()


@router.post("/agents", status_code=201)
async def add_agent(body: UrlIn, wb: Workbench = Depends(get_workbench)) -> AgentOut:
    return await wb.agents.add(body.url, body.card_path)


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, wb: Workbench = Depends(get_workbench)) -> AgentOut:
    return await wb.agents.get(agent_id)


@router.patch("/agents/{agent_id}")
async def patch_agent(
    agent_id: str, body: AgentPatch, wb: Workbench = Depends(get_workbench)
) -> AgentOut:
    return await wb.agents.set_interface(agent_id, body.selected_interface_url)


@router.post("/agents/{agent_id}/refresh")
async def refresh_agent(agent_id: str, wb: Workbench = Depends(get_workbench)) -> AgentOut:
    return await wb.agents.refresh_card(agent_id)


@router.post("/agents/{agent_id}/extended-card")
async def extended_card(agent_id: str, wb: Workbench = Depends(get_workbench)) -> ExtendedCardOut:
    return await wb.agents.get_extended_card(agent_id)


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, wb: Workbench = Depends(get_workbench)) -> Response:
    await wb.agents.remove(agent_id)
    return Response(status_code=204)
