"""Wiring of the core services."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from a2a_workbench.core.assistant.keys import ProviderKeyStore
from a2a_workbench.core.assistant.service import AssistantService
from a2a_workbench.core.auth.service import AuthService
from a2a_workbench.core.auth.store import CredentialStore
from a2a_workbench.core.auth.vault import Vault, load_vault_key
from a2a_workbench.core.blobs import BlobService
from a2a_workbench.core.bus import EventBus
from a2a_workbench.core.config import Settings
from a2a_workbench.core.conversations.service import ConversationService
from a2a_workbench.core.exchanges import ExchangeStore
from a2a_workbench.core.integrate.service import IntegrationService
from a2a_workbench.core.push.hooks import HookStore
from a2a_workbench.core.push.receiver import Receiver
from a2a_workbench.core.push.service import PushService
from a2a_workbench.core.registry.service import AgentService
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import DEFAULT_WORKSPACE_ID, Workspace
from a2a_workbench.core.tasks.service import TaskService


class Workbench:
    """All core services sharing one settings object, database and event bus."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.resolved_database_url)
        self.bus = EventBus()
        self.exchanges = ExchangeStore(self.db, self.bus)
        self.blobs = BlobService(self.db, settings.max_blob_bytes)
        vault = Vault(load_vault_key(settings))
        self.credentials = CredentialStore(self.db, vault)
        self.provider_keys = ProviderKeyStore(self.db, vault)
        self.auth = AuthService(self.credentials, self.exchanges)
        self.agents = AgentService(self.db, self.exchanges, self.auth)
        self.conversations = ConversationService(
            self.db, self.bus, self.exchanges, self.blobs, self.auth
        )
        self.tasks = TaskService(self.agents, self.exchanges, self.auth)
        self.push = PushService(self.tasks)
        self.tunnel_url: str | None = None
        self.hooks = HookStore(self.db, self.public_base_url)
        self.receiver = Receiver(self.db, self.hooks, self.conversations, self.bus)
        self.assistant = AssistantService(self)
        self.integrate = IntegrationService(self.agents)

    def public_base_url(self) -> str:
        """Base URL agents reach this server at: the setting, a tunnel, or the bind address."""
        if self.settings.public_base_url:
            return self.settings.public_base_url.rstrip("/")
        if self.tunnel_url:
            return self.tunnel_url.rstrip("/")
        host = (
            self.settings.host if self.settings.host not in ("0.0.0.0", "::", "") else "127.0.0.1"
        )
        return f"http://{host}:{self.settings.port}"

    async def start(self) -> None:
        """Create the state directory, the schema and the default workspace."""
        self.settings.home.mkdir(parents=True, exist_ok=True)
        await self.db.create_schema()
        async with self.db.sessions() as session:
            if await session.get(Workspace, DEFAULT_WORKSPACE_ID) is None:
                session.add(Workspace(id=DEFAULT_WORKSPACE_ID, name="Default"))
                await session.commit()

    async def close(self) -> None:
        """Stop Assistant turns and release database connections."""
        await self.assistant.close()
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
