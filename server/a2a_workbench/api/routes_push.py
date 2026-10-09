"""Push notification configs, deliveries, and the public URL / tunnel settings."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.push.receiver import DeliveryOut
from a2a_workbench.core.push.service import mask_config
from a2a_workbench.core.push.tunnel import TunnelUnavailableError
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api")


class ConfigIn(BaseModel):
    webhook: Literal["workbench", "custom"] = "workbench"
    url: str | None = None
    token: str | None = None
    auth_scheme: str | None = None
    auth_credentials: str | None = None


class PublicUrlIn(BaseModel):
    public_base_url: str | None = None


@router.get("/agents/{agent_id}/tasks/{task_id}/push-configs")
async def list_configs(
    agent_id: str,
    task_id: str,
    page_size: int | None = None,
    page_token: str | None = None,
    wb: Workbench = Depends(get_workbench),
) -> dict[str, Any]:
    return await wb.push.list(agent_id, task_id, page_size=page_size, page_token=page_token)


@router.post("/agents/{agent_id}/tasks/{task_id}/push-configs", status_code=201)
async def create_config(
    agent_id: str, task_id: str, body: ConfigIn, wb: Workbench = Depends(get_workbench)
) -> dict[str, Any]:
    if body.webhook == "workbench":
        return await wb.push.create_workbench(agent_id, task_id)
    if not body.url:
        raise HTTPException(
            422, detail={"category": "workbench", "message": "give the webhook url"}
        )
    config = await wb.push.create(
        agent_id,
        task_id,
        url=body.url,
        token=body.token,
        auth_scheme=body.auth_scheme,
        auth_credentials=body.auth_credentials,
    )
    return {"config": mask_config(config), "hook": None}


@router.get("/agents/{agent_id}/tasks/{task_id}/push-configs/{config_id}")
async def get_config(
    agent_id: str, task_id: str, config_id: str, wb: Workbench = Depends(get_workbench)
) -> dict[str, Any]:
    return await wb.push.get(agent_id, task_id, config_id)


@router.delete("/agents/{agent_id}/tasks/{task_id}/push-configs/{config_id}", status_code=204)
async def delete_config(
    agent_id: str, task_id: str, config_id: str, wb: Workbench = Depends(get_workbench)
) -> Response:
    await wb.push.delete(agent_id, task_id, config_id)
    return Response(status_code=204)


@router.get("/agents/{agent_id}/push/deliveries")
async def deliveries(agent_id: str, wb: Workbench = Depends(get_workbench)) -> list[DeliveryOut]:
    await wb.agents.get(agent_id)
    return await wb.receiver.deliveries(agent_id)


@router.get("/push/deliveries/{delivery_id}")
async def delivery(delivery_id: str, wb: Workbench = Depends(get_workbench)) -> DeliveryOut:
    found = await wb.receiver.delivery(delivery_id)
    if found is None:
        raise HTTPException(404, detail={"category": "workbench", "message": "no such delivery"})
    return found


async def _public(wb: Workbench) -> dict[str, Any]:
    import shutil

    url, source = await wb.public_url()
    return {
        "public_base_url": url,
        "source": source,
        "tunnel_running": wb.tunnel.running,
        "cloudflared_installed": shutil.which("cloudflared") is not None,
    }


@router.get("/settings/public-url")
async def get_public_url(wb: Workbench = Depends(get_workbench)) -> dict[str, Any]:
    return await _public(wb)


@router.put("/settings/public-url")
async def put_public_url(
    body: PublicUrlIn, wb: Workbench = Depends(get_workbench)
) -> dict[str, Any]:
    await wb.set_public_url(body.public_base_url)
    return await _public(wb)


@router.post("/settings/tunnel")
async def start_tunnel(wb: Workbench = Depends(get_workbench)) -> dict[str, Any]:
    try:
        await wb.set_tunnel_url(await wb.tunnel.start(wb.settings.port))
    except TunnelUnavailableError as exc:
        raise HTTPException(422, detail={"category": "workbench", "message": str(exc)}) from None
    return await _public(wb)


@router.delete("/settings/tunnel")
async def stop_tunnel(wb: Workbench = Depends(get_workbench)) -> dict[str, Any]:
    await wb.tunnel.stop()
    await wb.set_tunnel_url(None)
    return await _public(wb)
