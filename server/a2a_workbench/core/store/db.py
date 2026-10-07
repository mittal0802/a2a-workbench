"""Async database engine and sessions."""

from pathlib import Path

from sqlalchemy.engine import make_url
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
        """Create every table that does not exist yet."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        """Close all pooled connections."""
        await self.engine.dispose()
