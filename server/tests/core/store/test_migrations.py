import asyncio
import sqlite3

from sqlalchemy import text

from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import Base


def _url(path):
    return f"sqlite+aiosqlite:///{path}"


async def test_fresh_database_matches_models(tmp_path, schema_diff):
    db = Database(_url(tmp_path / "a.db"))
    await db.migrate()
    assert await schema_diff(db) == []
    await db.dispose()


async def test_migrate_is_idempotent(tmp_path):
    db = Database(_url(tmp_path / "a.db"))
    await db.migrate()
    await db.migrate()
    async with db.engine.connect() as conn:
        rev = (await conn.execute(text("select version_num from alembic_version"))).scalar_one()
    assert rev == "0001"
    await db.dispose()


async def test_legacy_database_is_upgraded_in_place(tmp_path, schema_diff):
    path = tmp_path / "legacy.db"
    legacy = Database(_url(path))
    async with legacy.engine.begin() as conn:  # a 0.1 database: create_all, one column missing
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("ALTER TABLE agent DROP COLUMN selected_interface_url")
        await conn.exec_driver_sql("INSERT INTO workspace (id, name) VALUES ('w1', 'Old')")
    await legacy.dispose()

    db = Database(_url(path))
    await db.migrate()
    assert await schema_diff(db) == []
    async with db.engine.connect() as conn:
        names = (await conn.execute(text("select name from workspace where id='w1'"))).all()
    assert names == [("Old",)]
    await db.dispose()


async def test_concurrent_migrate_on_sqlite(tmp_path):
    path = tmp_path / "race.db"
    dbs = [Database(_url(path)) for _ in range(4)]
    await asyncio.gather(*(d.migrate() for d in dbs))
    assert sqlite3.connect(path).execute("select count(*) from alembic_version").fetchone() == (1,)
    for d in dbs:
        await d.dispose()
