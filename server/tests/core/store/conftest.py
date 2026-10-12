import os
import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import make_url

from a2a_workbench.core.store.models import Base


@pytest.fixture
def schema_diff():
    """Differences between a database's schema and the ORM models (empty when in sync)."""

    async def diff(db):
        async with db.engine.connect() as conn:
            return await conn.run_sync(
                lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata)
            )

    return diff


@pytest.fixture
async def pg_url():
    """A SQLAlchemy URL to a new, empty Postgres database, dropped afterwards."""
    base = os.environ.get("A2AW_TEST_POSTGRES_URL")
    if not base:
        pytest.skip("A2AW_TEST_POSTGRES_URL not set")
    import asyncpg

    url = make_url(base)
    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    name = f"t_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(dsn)
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()
