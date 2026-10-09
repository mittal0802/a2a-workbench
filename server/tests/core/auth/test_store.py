import os

import pytest

from a2a_workbench.core.auth.store import CredentialStore
from a2a_workbench.core.auth.vault import Vault


@pytest.fixture
async def agent(wb, zoo):
    return await wb.agents.add(zoo.base_url)


async def test_put_get_list_delete(wb, agent):
    store = wb.credentials
    await store.put(agent.id, "apiKey", "api_key", {"value": "abcdef123a91"})
    assert (await store.get(agent.id, "apiKey"))["value"] == "abcdef123a91"
    infos = await store.list(agent.id)
    assert [(i.scheme_name, i.kind, i.preview, i.readable) for i in infos] == [
        ("apiKey", "api_key", "••••3a91", True)
    ]
    await store.put(agent.id, "apiKey", "api_key", {"value": "zzzz9999"})
    assert (await store.get(agent.id, "apiKey"))["value"] == "zzzz9999"
    await store.delete(agent.id, "apiKey")
    assert await store.get(agent.id, "apiKey") is None and await store.list(agent.id) == []


async def test_previews_never_reveal_secrets(wb, agent):
    store = wb.credentials
    await store.put(
        agent.id, "basic", "http_basic", {"username": "keshav", "password": "pw-secret"}
    )
    await store.put(agent.id, "oauth", "oauth2", {"access_token": "tok-123456", "scopes": ["read"]})
    previews = {i.scheme_name: i.preview for i in await store.list(agent.id)}
    assert previews["basic"] == "keshav · ••••"
    assert "tok-123456" not in previews["oauth"] and "read" in previews["oauth"]


async def test_unreadable_credentials_are_reported_not_raised(wb, agent):
    await wb.credentials.put(agent.id, "apiKey", "api_key", {"value": "x"})
    other = CredentialStore(wb.db, Vault(os.urandom(32)))
    assert await other.get(agent.id, "apiKey") is None
    assert [i.readable for i in await other.list(agent.id)] == [False]


async def test_removing_agent_removes_credentials(wb, agent):
    await wb.credentials.put(agent.id, "apiKey", "api_key", {"value": "x"})
    await wb.agents.remove(agent.id)
    assert await wb.credentials.list(agent.id) == []
