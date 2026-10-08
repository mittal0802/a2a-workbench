"""Security and credential endpoints."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.auth.service import SecurityOverview
from a2a_workbench.core.auth.store import CredentialInfo
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api/agents/{agent_id}")


class CredentialIn(BaseModel):
    kind: Literal["api_key", "http_basic", "http_bearer", "oauth2", "mtls"]
    value: str | None = None
    username: str | None = None
    password: str | None = None
    token: str | None = None
    access_token: str | None = None
    cert_pem: str | None = None
    key_pem: str | None = None
    ca_pem: str | None = None


@router.get("/security")
async def security(agent_id: str, wb: Workbench = Depends(get_workbench)) -> SecurityOverview:
    agent = await wb.agents.row(agent_id)
    return await wb.auth.overview(agent_id, card_from_json(agent.card))


@router.put("/credentials/{scheme}")
async def put_credential(
    agent_id: str, scheme: str, body: CredentialIn, wb: Workbench = Depends(get_workbench)
) -> CredentialInfo:
    agent = await wb.agents.row(agent_id)
    secret: dict[str, Any] = body.model_dump(exclude={"kind"}, exclude_none=True)
    return await wb.auth.set_credential(
        agent_id, card_from_json(agent.card), scheme, body.kind, secret
    )


@router.delete("/credentials/{scheme}", status_code=204)
async def delete_credential(
    agent_id: str, scheme: str, wb: Workbench = Depends(get_workbench)
) -> Response:
    await wb.agents.row(agent_id)
    await wb.credentials.delete(agent_id, scheme)
    return Response(status_code=204)
