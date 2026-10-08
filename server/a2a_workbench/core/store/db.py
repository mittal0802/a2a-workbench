"""Async database engine and sessions."""

from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from a2a_workbench.core.store.models import Base


class Database:
    """Owns one async SQLAlchemy engine and a session factory bound to it.

    For SQLite file URLs the parent directory is created if missing.
    """

    def __init__(self, url: str) -> None:
        parsed = make_url(url)
        if parsed.get_backend_name() == "sqlite" and parsed.database:
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_async_engine(url)
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def create_schema(self) -> None:
        """Create missing tables, and add missing columns to existing tables.

        Added columns are created nullable; this covers additive schema
        changes between versions.
        """
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_add_missing_columns)

    async def dispose(self) -> None:
        """Close all pooled connections."""
        await self.engine.dispose()


def _add_missing_columns(conn: Connection) -> None:
    inspector = inspect(conn)
    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            column_type = column.type.compile(dialect=conn.dialect)
            conn.exec_driver_sql(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'
            )
