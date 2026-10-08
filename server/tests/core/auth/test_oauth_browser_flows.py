import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.fixtures.idp import IDP_CLIENT, IDP_USER, IdpServer
from a2a_workbench.fixtures.runner import ZooServer

REDIRECT = "http://127.0.0.1:8484/oauth/callback"


@pytest.fixture(scope="module")
def idp():
    with IdpServer() as server:
        yield server


@pytest.fixture(scope="module")
def oauth_zoo(idp):
    with ZooServer(auth="oauth", idp=idp.idp, grpc=False) as zoo:
        yield zoo


def _approve(authorize_url: str) -> str:
    """Act as the user's browser on the mock provider; return the redirect location."""
    page = httpx.get(authorize_url)
    form = dict(parse_qs(urlparse(authorize_url).query))
    data = {k: v[0] for k, v in form.items()}
    approved = httpx.post(authorize_url.split("?")[0], data=data, follow_redirects=False)
    assert page.status_code == 200 and approved.status_code == 302
    return approved.headers["location"]


async def _chat_ok(wb, agent):
    conv = await wb.conversations.create(agent.id)
    events = [
        e
        async for e in wb.conversations.send(
            conv.id, [TextPartInput(text="echo ok")], SendOptions(stream=False)
        )
    ]
    return events[-1].data.get("state") == "completed"


async def test_authorization_code_with_pkce(wb, oauth_zoo):
    agent = await wb.agents.add(oauth_zoo.base_url)
    start = await wb.auth.start_browser_flow(
        agent.id,
        "oauthCode",
        client_id=IDP_CLIENT["id"],
        scopes=["a2a:invoke"],
        redirect_uri=REDIRECT,
        card=card_from_json(agent.card),
    )
    assert (
        "code_challenge=" in start.authorize_url
        and "code_challenge_method=S256" in start.authorize_url
    )
    location = await asyncio.to_thread(_approve, start.authorize_url)
    q = parse_qs(urlparse(location).query)
    info = await wb.auth.finish_browser_flow(state=q["state"][0], code=q["code"][0])
    assert info.scheme_name == "oauthCode" and await _chat_ok(wb, agent)


async def test_callback_with_unknown_state_is_rejected(wb):
    from a2a_workbench.core.auth.service import CredentialError

    with pytest.raises(CredentialError):
        await wb.auth.finish_browser_flow(state="forged", code="x")


async def test_implicit_flow_token_from_fragment(wb, oauth_zoo):
    agent = await wb.agents.add(oauth_zoo.base_url)
    start = await wb.auth.start_browser_flow(
        agent.id,
        "oauthImplicit",
        client_id=IDP_CLIENT["id"],
        scopes=["a2a:invoke"],
        redirect_uri=REDIRECT,
        card=card_from_json(agent.card),
    )
    location = await asyncio.to_thread(_approve, start.authorize_url)
    fragment = parse_qs(urlparse(location).fragment)
    await wb.auth.finish_browser_flow(
        state=fragment["state"][0],
        access_token=fragment["access_token"][0],
        expires_in=int(fragment["expires_in"][0]),
        scope=fragment["scope"][0],
    )
    assert await _chat_ok(wb, agent)


async def test_device_code_flow(wb, oauth_zoo, idp):
    agent = await wb.agents.add(oauth_zoo.base_url)
    device = await wb.auth.start_device_flow(
        agent.id,
        "oauthDevice",
        client_id=IDP_CLIENT["id"],
        scopes=["a2a:invoke"],
        card=card_from_json(agent.card),
    )
    assert device.user_code and device.verification_uri.endswith("/device")
    assert await wb.auth.poll_device_flow(device.flow_id) == "pending"
    await asyncio.to_thread(
        httpx.post, device.verification_uri, data={"user_code": device.user_code}
    )
    for _ in range(20):
        if await wb.auth.poll_device_flow(device.flow_id) == "signed_in":
            break
        await asyncio.sleep(0.1)
    assert await _chat_ok(wb, agent)


async def test_password_flow(wb, oauth_zoo):
    agent = await wb.agents.add(oauth_zoo.base_url)
    await wb.auth.sign_in(
        agent.id,
        "oauthPassword",
        flow="password",
        client_id=IDP_CLIENT["id"],
        client_secret=IDP_CLIENT["secret"],
        username=IDP_USER["username"],
        password=IDP_USER["password"],
        scopes=["a2a:invoke"],
        card=card_from_json(agent.card),
    )
    assert await _chat_ok(wb, agent)


async def test_openid_connect_sign_in_uses_discovery(wb, idp):
    async with ZooServer(auth="oidc", idp=idp.idp, grpc=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        card = card_from_json(agent.card)
        assert (
            card.security_schemes["oidc"].WhichOneof("scheme") == "open_id_connect_security_scheme"
        )
        start = await wb.auth.start_browser_flow(
            agent.id,
            "oidc",
            client_id=IDP_CLIENT["id"],
            scopes=["openid", "a2a:invoke"],
            redirect_uri=REDIRECT,
            card=card,
        )
        assert start.authorize_url.startswith(f"{idp.base_url}/authorize?")
        location = await asyncio.to_thread(_approve, start.authorize_url)
        q = parse_qs(urlparse(location).query)
        await wb.auth.finish_browser_flow(state=q["state"][0], code=q["code"][0])
        stored = await wb.credentials.get(agent.id, "oidc")
        assert stored["id_token"]
        assert await _chat_ok(wb, agent)
