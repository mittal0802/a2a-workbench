"""Wiring of the core services."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from a2a_workbench.core.blobs import BlobService
from a2a_workbench.core.bus import EventBus
from a2a_workbench.core.config import Settings
from a2a_workbench.core.conversations.service import ConversationService
from a2a_workbench.core.exchanges import ExchangeStore
from a2a_workbench.core.registry.service import AgentService
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import DEFAULT_WORKSPACE_ID, Workspace


class Workbench:
    """All core services sharing one settings object, database and event bus."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.resolved_database_url)
        self.bus = EventBus()
        self.exchanges = ExchangeStore(self.db, self.bus)
        self.blobs = BlobService(self.db, settings.max_blob_bytes)
        self.agents = AgentService(self.db, self.exchanges)
        self.conversations = ConversationService(self.db, self.bus, self.exchanges, self.blobs)

    async def start(self) -> None:
        """Create the state directory, the schema and the default workspace."""
        self.settings.home.mkdir(parents=True, exist_ok=True)
        await self.db.create_schema()
        async with self.db.sessions() as session:
            if await session.get(Workspace, DEFAULT_WORKSPACE_ID) is None:
                session.add(Workspace(id=DEFAULT_WORKSPACE_ID, name="Default"))
                await session.commit()

    async def close(self) -> None:
        """Release database connections."""
        await self.db.dispose()

    @classmethod
    @asynccontextmanager
    async def open(cls, settings: Settings) -> AsyncIterator["Workbench"]:
        """Yield a started Workbench and close it on exit."""
        workbench = cls(settings)
        await workbench.start()
        try:
            yield workbench
        finally:
            await workbench.close()
