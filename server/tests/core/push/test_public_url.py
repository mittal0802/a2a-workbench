import pytest

from a2a_workbench.core.config import Settings
from a2a_workbench.core.workbench import Workbench


@pytest.fixture(autouse=True)
def _no_env_url(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("A2AW_PUBLIC_BASE_URL", raising=False)


async def test_every_process_sees_the_running_servers_address(monkeypatch):
    monkeypatch.setenv("A2AW_PORT", "9000")
    async with Workbench.open(Settings()) as server:
        await server.announce_serving()
        monkeypatch.setenv("A2AW_PORT", "8484")
        async with Workbench.open(Settings()) as cli:
            assert await cli.public_url() == ("http://127.0.0.1:9000", "local")
            await server.set_public_url("https://hooks.example/")
            assert await cli.public_url() == ("https://hooks.example", "setting")
            hook = await cli.hooks.create("agent-1", task_id="t")
            assert hook.url.startswith("https://hooks.example/hooks/")
            await server.set_public_url(None)
            await server.set_tunnel_url("https://x.trycloudflare.com")
            assert await cli.public_url() == ("https://x.trycloudflare.com", "tunnel")
            assert (await cli.hooks.get(hook.id)).url == hook.url


async def test_environment_setting_wins(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://env.example")
    async with Workbench.open(Settings()) as wb:
        await wb.set_tunnel_url("https://x.trycloudflare.com")
        assert await wb.public_url() == ("https://env.example", "setting")


async def test_workbench_webhook_reports_a_local_only_address(wb, zoo):
    from a2a_workbench.core.conversations.options import SendOptions
    from a2a_workbench.core.conversations.parts import TextPartInput

    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    events = [
        e
        async for e in wb.conversations.send(
            conv.id,
            [TextPartInput(text="slow 10")],
            SendOptions(stream=False, return_immediately=True),
        )
    ]
    task = next(e.task_id for e in events if e.task_id)
    out = await wb.push.create_workbench(agent.id, task)
    assert out["webhook_source"] == "local" and "only reachable from this machine" in out["warning"]
    await wb.set_public_url("https://hooks.example")
    out = await wb.push.create_workbench(agent.id, task)
    assert out["webhook_source"] == "setting" and "warning" not in out
