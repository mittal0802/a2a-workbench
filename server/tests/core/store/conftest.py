import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

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
