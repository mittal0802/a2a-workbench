from sqlalchemy import select

from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import DEFAULT_WORKSPACE_ID, Agent


async def test_create_schema_and_insert(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'nested' / 't.db'}")
    await db.migrate()
    async with db.sessions() as s:
        s.add(
            Agent(
                workspace_id=DEFAULT_WORKSPACE_ID,
                name="x",
                base_url="http://x",
                card={"name": "x"},
                signature_status="unsigned",
            )
        )
        await s.commit()
        agent = (await s.execute(select(Agent))).scalar_one()
    assert len(agent.id) == 32
    assert agent.created_at is not None
    assert agent.card == {"name": "x"}
    await db.dispose()
