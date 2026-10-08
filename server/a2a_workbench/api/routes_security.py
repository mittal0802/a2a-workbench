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


class OAuthSignIn(BaseModel):
    flow: Literal["client_credentials", "password"]
    client_id: str
    client_secret: str | None = None
    scopes: list[str] = []
    auth_method: Literal["client_secret_post", "client_secret_basic"] = "client_secret_post"
    username: str | None = None
    password: str | None = None


@router.post("/oauth/{scheme}/sign-in")
async def oauth_sign_in(
    agent_id: str, scheme: str, body: OAuthSignIn, wb: Workbench = Depends(get_workbench)
) -> CredentialInfo:
    agent = await wb.agents.row(agent_id)
    return await wb.auth.sign_in(
        agent_id,
        scheme,
        flow=body.flow,
        client_id=body.client_id,
        client_secret=body.client_secret,
        scopes=body.scopes,
        auth_method=body.auth_method,
        username=body.username,
        password=body.password,
        card=card_from_json(agent.card),
    )


@router.delete("/credentials/{scheme}", status_code=204)
async def delete_credential(
    agent_id: str, scheme: str, wb: Workbench = Depends(get_workbench)
) -> Response:
    await wb.agents.row(agent_id)
    await wb.credentials.delete(agent_id, scheme)
    return Response(status_code=204)
