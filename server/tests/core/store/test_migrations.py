import asyncio
import sqlite3

import pytest
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


async def test_migrate_creates_the_default_workspace(tmp_path):
    from a2a_workbench.core.store.models import DEFAULT_WORKSPACE_ID

    db = Database(_url(tmp_path / "a.db"))
    await db.migrate()
    await db.migrate()
    async with db.engine.connect() as conn:
        rows = (await conn.execute(text("select id from workspace"))).all()
    assert rows == [(DEFAULT_WORKSPACE_ID,)]
    await db.dispose()


def test_concurrent_first_starts_after_upgrade(tmp_path):
    import subprocess
    import sys

    script = (
        "import asyncio, sys\n"
        "from a2a_workbench.core.config import Settings\n"
        "from a2a_workbench.core.workbench import Workbench\n"
        "async def main():\n"
        "    async with Workbench.open(Settings(home=sys.argv[1])):\n"
        "        pass\n"
        "asyncio.run(main())\n"
    )
    for round_ in range(3):
        home = tmp_path / f"h{round_}"
        home.mkdir()
        asyncio.run(_upgrade(home / "workbench.db"))
        procs = [
            subprocess.Popen([sys.executable, "-c", script, str(home)], stderr=subprocess.PIPE)
            for _ in range(6)
        ]
        errors = [p.communicate()[1].decode() for p in procs if p.wait() != 0]
        assert errors == [], errors[0][-300:]


async def _upgrade(path):
    db = Database(_url(path))
    await db.migrate()
    await db.dispose()


@pytest.mark.parametrize("url", ["sqlite+aiosqlite://", "sqlite+aiosqlite:///:memory:"])
async def test_in_memory_database_is_migrated(url):
    from a2a_workbench.core.config import Settings
    from a2a_workbench.core.workbench import Workbench

    async with Workbench.open(Settings(database_url=url)) as wb:
        assert await wb.agents.list() == []
