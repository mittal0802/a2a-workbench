import asyncio
import json
import os

import pytest
import uvicorn

from a2a_workbench.api.app import create_app
from a2a_workbench.core.config import Settings
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.fixtures.runner import free_port


@pytest.fixture
async def served(monkeypatch):
    """A real Workbench API server in this event loop, which agents can POST notifications to."""
    port = free_port()
    monkeypatch.setenv("A2AW_PORT", str(port))
    app = create_app(Settings())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    yield app.state.workbench
    server.should_exit = True
    await task


async def _wait_for(predicate, attempts=100):
    for _ in range(attempts):
        if result := await predicate():
            return result
        await asyncio.sleep(0.1)
    raise AssertionError("timed out")


async def test_inline_push_binds_to_the_new_task(served, zoo):
    wb = served
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    events = [
        e
        async for e in wb.conversations.send(
            conv.id,
            [TextPartInput(text="long")],
            SendOptions(stream=False, return_immediately=True, push=True),
        )
    ]
    task_id = next(e.task_id for e in events if e.task_id)
    hooks = await wb.hooks.list(agent.id)
    assert len(hooks) == 1 and hooks[0].task_id == task_id and hooks[0].conversation_id == conv.id

    async def completed():
        evs = await wb.conversations.events(conv.id)
        return (
            evs if any(e.kind == "push" and e.data["state"] == "completed" for e in evs) else None
        )

    evs = await _wait_for(completed)
    assert all(e.task_id == task_id for e in evs if e.kind == "push")
    deliveries = await wb.receiver.deliveries(agent.id)
    assert deliveries and all(d.verdict == "accepted" for d in deliveries)
    sent = await wb.exchanges.list(conversation_id=conv.id)
    record = await wb.exchanges.get(sent[0]["id"])
    cfg = json.loads(record["request_body"])["params"]["configuration"][
        "taskPushNotificationConfig"
    ]
    assert cfg["url"].endswith(f"/hooks/{hooks[0].id}")
    assert cfg["token"] == "••••" and cfg["authentication"]["credentials"] == "••••"


def test_public_base_url_precedence(monkeypatch):
    from a2a_workbench.core.workbench import Workbench

    monkeypatch.setenv("A2AW_PORT", "9123")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("A2AW_PUBLIC_BASE_URL", raising=False)
    wb = Workbench(Settings())
    assert wb.public_base_url() == "http://127.0.0.1:9123"
    wb.tunnel.url = "https://x.trycloudflare.com"
    assert wb.public_base_url() == "https://x.trycloudflare.com"
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://hooks.example/")
    assert Workbench(Settings()).public_base_url() == "https://hooks.example"
    assert os.environ["A2AW_PORT"] == "9123"
