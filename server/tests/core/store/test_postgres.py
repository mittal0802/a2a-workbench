import asyncio
from datetime import UTC, datetime

from sqlalchemy import select, text

from a2a_workbench.core.config import Settings
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import (
    Agent,
    Conversation,
    ExchangeRow,
    TimelineEventRow,
    Workspace,
)
from a2a_workbench.core.workbench import Workbench


async def test_fresh_postgres_matches_models(pg_url, schema_diff):
    db = Database(pg_url)
    await db.migrate()
    assert await schema_diff(db) == []
    await db.dispose()


async def test_concurrent_migrate_on_postgres(pg_url):
    dbs = [Database(pg_url) for _ in range(4)]
    await asyncio.gather(*(d.migrate() for d in dbs))
    async with dbs[0].engine.connect() as conn:
        rows = (await conn.execute(text("select version_num from alembic_version"))).all()
    assert rows == [("0001",)]
    for d in dbs:
        await d.dispose()


async def test_long_external_values_on_postgres(pg_url):
    db = Database(pg_url)
    await db.migrate()
    name, task_id, error, url = "n" * 600, "t" * 300, "e" * 5000, "http://x/" + "p" * 3000
    async with db.sessions() as s:
        s.add(Workspace(id="w" * 32, name=name))
        await s.flush()
        agent = Agent(
            workspace_id="w" * 32, name=name, base_url=url, card={}, signature_status="unsigned"
        )
        s.add(agent)
        await s.flush()
        conv = Conversation(workspace_id="w" * 32, agent_id=agent.id, title=name, task_id=task_id)
        s.add(conv)
        await s.flush()
        s.add(
            TimelineEventRow(conversation_id=conv.id, seq=1, kind="task", task_id=task_id, data={})
        )
        s.add(
            ExchangeRow(
                id="x" * 32,
                agent_id=agent.id,
                operation="send_message",
                started_at=datetime.now(UTC),
                error=error,
                record={},
            )
        )
        await s.commit()
    async with db.sessions() as s:
        assert await s.scalar(select(Agent.name)) == name
        assert await s.scalar(select(Agent.base_url)) == url
        assert await s.scalar(select(TimelineEventRow.task_id)) == task_id
        assert await s.scalar(select(ExchangeRow.error)) == error
    await db.dispose()


async def test_workbench_lifecycle_on_postgres(pg_url, zoo):
    async with Workbench.open(Settings(database_url=pg_url)) as wb:
        agent = await wb.agents.add(zoo.base_url)
        conv = await wb.conversations.create(agent.id)
        events = [
            e
            async for e in wb.conversations.send(conv.id, [TextPartInput(text="hi")], SendOptions())
        ]
        assert events[-1].kind == "status" and events[-1].data["state"] == "completed"
        progress = [e async for e in wb.health.run(agent.id, areas=["A"])]
        run = await wb.health.get(progress[0].run_id)
        assert run.status == "done" and run.results
