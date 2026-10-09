import asyncio
import json

import pytest

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.fixtures.idp import IDP_CLIENT, IdpServer
from a2a_workbench.fixtures.runner import ZooServer


def _card(agent):
    from a2a_workbench.core.a2a_json import card_from_json

    return card_from_json(agent.card)


async def _send(wb, conv_id, text):
    return [
        e
        async for e in wb.conversations.send(
            conv_id, [TextPartInput(text=text)], SendOptions(stream=False)
        )
    ]


@pytest.fixture(scope="module")
def idp():
    with IdpServer(token_lifetime=2) as server:
        yield server


@pytest.fixture(scope="module")
def oauth_zoo(idp):
    with ZooServer(auth="oauth", idp=idp.idp, grpc=False) as zoo:
        yield zoo


async def test_client_credentials_sign_in_then_chat(wb, oauth_zoo):
    agent = await wb.agents.add(oauth_zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    assert (await _send(wb, conv.id, "echo hi"))[-1].data["category"] == "auth"
    info = await wb.auth.sign_in(
        agent.id,
        "oauth",
        flow="client_credentials",
        client_id=IDP_CLIENT["id"],
        client_secret=IDP_CLIENT["secret"],
        scopes=["a2a:invoke"],
        card=_card(agent),
    )
    assert info.kind == "oauth2" and "a2a:invoke" in info.preview
    assert (await _send(wb, conv.id, "echo hi"))[-1].data["state"] == "completed"
    stored = json.dumps(
        [await wb.exchanges.get(e["id"]) for e in await wb.exchanges.list(limit=1000)]
    )
    assert IDP_CLIENT["secret"] not in stored


async def test_expired_token_is_renewed_before_the_call(wb, oauth_zoo):
    agent = await wb.agents.add(oauth_zoo.base_url)
    await wb.auth.sign_in(
        agent.id,
        "oauth",
        flow="client_credentials",
        client_id=IDP_CLIENT["id"],
        client_secret=IDP_CLIENT["secret"],
        scopes=["a2a:invoke"],
        card=_card(agent),
    )
    first = (await wb.credentials.get(agent.id, "oauth"))["access_token"]
    await asyncio.sleep(2.2)
    conv = await wb.conversations.create(agent.id)
    assert (await _send(wb, conv.id, "echo later"))[-1].data["state"] == "completed"
    assert (await wb.credentials.get(agent.id, "oauth"))["access_token"] != first


async def test_bad_client_secret_is_auth_error(wb, oauth_zoo):
    agent = await wb.agents.add(oauth_zoo.base_url)
    with pytest.raises(AgentCallError) as info:
        await wb.auth.sign_in(
            agent.id,
            "oauth",
            flow="client_credentials",
            client_id=IDP_CLIENT["id"],
            client_secret="wrong",
            scopes=[],
            card=_card(agent),
        )
    assert (
        info.value.classified["category"] == "auth"
        and info.value.classified["reason"] == "invalid_client"
    )


async def test_each_flow_is_its_own_scheme_with_scopes(wb, oauth_zoo):
    agent = await wb.agents.add(oauth_zoo.base_url)
    overview = await wb.auth.overview(agent.id, _card(agent))
    flows = {s.name: s.flows for s in overview.schemes}
    assert flows == {
        "oauth": ["client_credentials"],
        "oauthCode": ["authorization_code"],
        "oauthDevice": ["device_code"],
        "oauthPassword": ["password"],
        "oauthImplicit": ["implicit"],
    }
    assert all("a2a:invoke" in s.scopes for s in overview.schemes)
    assert sorted(overview.requirements) == sorted([[n] for n in flows])


async def test_failed_sign_in_explains_unsupported_grant_from_metadata(wb):
    with (
        IdpServer(grants=["authorization_code", "refresh_token"], error_style="custom") as idp,
        ZooServer(auth="oauth", idp=idp.idp, grpc=False) as zoo,
    ):
        agent = await wb.agents.add(zoo.base_url)
        with pytest.raises(AgentCallError) as info:
            await wb.auth.sign_in(
                agent.id,
                "oauth",
                flow="client_credentials",
                client_id=IDP_CLIENT["id"],
                client_secret=IDP_CLIENT["secret"],
                scopes=[],
                card=_card(agent),
            )
    c = info.value.classified
    assert c["category"] == "auth"
    assert '"grant_type" must be one of' in c["message"]
    assert "does not list client_credentials" in c["hint"]


async def test_skill_scope_enforced(wb, oauth_zoo):
    agent = await wb.agents.add(oauth_zoo.base_url)
    await wb.auth.sign_in(
        agent.id,
        "oauth",
        flow="client_credentials",
        client_id=IDP_CLIENT["id"],
        client_secret=IDP_CLIENT["secret"],
        scopes=["a2a:invoke"],
        card=_card(agent),
    )
    conv = await wb.conversations.create(agent.id)
    held = [
        e
        async for e in wb.conversations.send(
            conv.id, [TextPartInput(text="hold AI175")], SendOptions(stream=False, skill_id="hold")
        )
    ]
    assert held[-1].data["state"] == "auth_required"
    await wb.auth.sign_in(
        agent.id,
        "oauth",
        flow="client_credentials",
        client_id=IDP_CLIENT["id"],
        client_secret=IDP_CLIENT["secret"],
        scopes=["a2a:invoke", "booking.write"],
        card=_card(agent),
    )
    conv2 = await wb.conversations.create(agent.id)
    ok = [
        e
        async for e in wb.conversations.send(
            conv2.id, [TextPartInput(text="hold AI175")], SendOptions(stream=False, skill_id="hold")
        )
    ]
    assert ok[-1].data["state"] == "completed"


async def _signed_in(wb, oauth_zoo):
    agent = await wb.agents.add(oauth_zoo.base_url)
    await wb.auth.sign_in(
        agent.id,
        "oauth",
        flow="client_credentials",
        client_id=IDP_CLIENT["id"],
        client_secret=IDP_CLIENT["secret"],
        scopes=["a2a:invoke"],
        card=_card(agent),
    )
    return agent


async def test_concurrent_renewals_share_one_refresh(wb, oauth_zoo):
    agent = await _signed_in(wb, oauth_zoo)
    first = (await wb.credentials.get(agent.id, "oauth"))["access_token"]
    await asyncio.sleep(2.2)
    plans = await asyncio.gather(*(wb.auth.plan(agent.id, _card(agent)) for _ in range(4)))
    headers = {p.headers["Authorization"] for p in plans}
    assert len(headers) == 1 and headers != {f"Bearer {first}"}


async def test_failed_renewal_asks_to_sign_in_again(wb, oauth_zoo, idp):
    agent = await _signed_in(wb, oauth_zoo)
    idp.idp.refresh_tokens.clear()
    await asyncio.sleep(2.2)
    overview = await wb.auth.overview(agent.id, _card(agent))
    assert overview.status == "sign_in_needed"
    info = next(s.credential for s in overview.schemes if s.name == "oauth")
    assert info.renewal_error and "invalid_grant" in info.renewal_error
    assert "oauth" in overview.expired
