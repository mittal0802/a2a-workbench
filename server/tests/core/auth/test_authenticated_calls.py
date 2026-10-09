import json

import pytest

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.fixtures.auth import ZOO_SECRETS
from a2a_workbench.fixtures.runner import ZooServer

CREDS = {
    "apikey-header": [("apiKey", "api_key", {"value": ZOO_SECRETS["api_key"]})],
    "apikey-custom": [("apiKeyCustom", "api_key", {"value": ZOO_SECRETS["api_key"]})],
    "apikey-query": [("apiKeyQuery", "api_key", {"value": ZOO_SECRETS["api_key"]})],
    "apikey-cookie": [("apiKeyCookie", "api_key", {"value": ZOO_SECRETS["api_key"]})],
    "basic": [
        (
            "basic",
            "http_basic",
            {"username": ZOO_SECRETS["username"], "password": ZOO_SECRETS["password"]},
        )
    ],
    "bearer": [("bearer", "http_bearer", {"token": ZOO_SECRETS["token"]})],
    "and": [
        ("apiKey", "api_key", {"value": ZOO_SECRETS["api_key"]}),
        ("bearer", "http_bearer", {"token": ZOO_SECRETS["token"]}),
    ],
}


async def _send(wb, conv_id, text, **opts):
    return [
        e
        async for e in wb.conversations.send(
            conv_id, [TextPartInput(text=text)], SendOptions(**opts)
        )
    ]


@pytest.mark.parametrize("mode", list(CREDS))
@pytest.mark.parametrize("binding", ["JSONRPC", "HTTP+JSON", "GRPC"])
async def test_signed_in_chat_works_and_anonymous_is_auth_error(wb, mode, binding):
    if binding == "GRPC" and mode in ("apikey-query",):
        pytest.skip("gRPC has no query string")
    async with ZooServer(auth=mode) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        iface = next(i for i in agent.interfaces if i.binding == binding)
        await wb.agents.set_interface(agent.id, iface.url)
        conv = await wb.conversations.create(agent.id)
        anonymous = await _send(wb, conv.id, "echo hi", stream=False)
        assert anonymous[-1].kind == "error" and anonymous[-1].data["category"] == "auth"
        for scheme, kind, secret in CREDS[mode]:
            await wb.credentials.put(agent.id, scheme, kind, secret)
        ok = await _send(wb, conv.id, "echo hi", stream=False)
        assert ok[-1].data.get("state") == "completed"


async def test_secrets_absent_from_exchanges_and_api(wb):
    async with ZooServer(auth="and", grpc=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        for scheme, kind, secret in CREDS["and"]:
            await wb.credentials.put(agent.id, scheme, kind, secret)
        conv = await wb.conversations.create(agent.id)
        await _send(wb, conv.id, "stream")
        dump = json.dumps(
            [await wb.exchanges.get(e["id"]) for e in await wb.exchanges.list(agent_id=agent.id)]
        )
        dump += json.dumps([i.model_dump(mode="json") for i in await wb.credentials.list(agent.id)])
        dump += json.dumps(
            [e.model_dump(mode="json") for e in await wb.conversations.events(conv.id)]
        )
        assert ZOO_SECRETS["api_key"] not in dump and ZOO_SECRETS["token"] not in dump


async def test_query_api_key_is_redacted_in_recorded_url(wb):
    async with ZooServer(auth="apikey-query", grpc=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        await wb.credentials.put(
            agent.id, "apiKeyQuery", "api_key", {"value": ZOO_SECRETS["api_key"]}
        )
        conv = await wb.conversations.create(agent.id)
        await _send(wb, conv.id, "echo q", stream=False)
        urls = [e["url"] for e in await wb.exchanges.list(agent_id=agent.id)]
        assert any("api_key=" in u for u in urls) and all(
            ZOO_SECRETS["api_key"] not in u for u in urls
        )


async def test_tasks_and_extended_card_are_authenticated(wb):
    async with ZooServer(auth="bearer", grpc=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        await wb.credentials.put(agent.id, "bearer", "http_bearer", {"token": ZOO_SECRETS["token"]})
        conv = await wb.conversations.create(agent.id)
        await _send(wb, conv.id, "echo t", stream=False)
        task_id = (await wb.conversations.get(conv.id)).task_id
        assert (await wb.tasks.get(agent.id, task_id))["state"] == "completed"
        assert any(
            d["path"] == "skills[visa]" for d in (await wb.agents.get_extended_card(agent.id)).diff
        )


@pytest.mark.parametrize("binding", ["JSONRPC", "HTTP+JSON", "GRPC"])
async def test_api_key_in_a_custom_header_is_redacted(wb, binding):
    async with ZooServer(auth="apikey-custom") as zoo:
        agent = await wb.agents.add(zoo.base_url)
        iface = next(i for i in agent.interfaces if i.binding == binding)
        await wb.agents.set_interface(agent.id, iface.url)
        await wb.credentials.put(
            agent.id, "apiKeyCustom", "api_key", {"value": ZOO_SECRETS["api_key"]}
        )
        conv = await wb.conversations.create(agent.id)
        events = await _send(wb, conv.id, "echo hi", stream=False)
        assert events[-1].data.get("state") == "completed"
        records = [
            await wb.exchanges.get(e["id"]) for e in await wb.exchanges.list(agent_id=agent.id)
        ]
        sent = [r for r in records if "ocp-apim-subscription-key" in r["request_headers"]]
        assert sent and all(
            r["request_headers"]["ocp-apim-subscription-key"] == "••••" for r in sent
        )
        assert ZOO_SECRETS["api_key"] not in json.dumps(records)
