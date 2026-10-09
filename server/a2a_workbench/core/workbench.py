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
from a2a_workbench.core.kv import SettingsStore
from a2a_workbench.core.push.hooks import HookStore
from a2a_workbench.core.push.receiver import Receiver
from a2a_workbench.core.push.service import PushService
from a2a_workbench.core.push.tunnel import Tunnel
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
        self.tunnel = Tunnel()
        self.kv = SettingsStore(self.db)
        self.hooks = HookStore(self.db, self._hook_base)
        self.conversations.hooks = self.hooks
        self.push = PushService(self.tasks, self.hooks, self.public_url)
        self.receiver = Receiver(self.db, self.hooks, self.conversations, self.bus)
        self.assistant = AssistantService(self)
        self.integrate = IntegrationService(self.agents)

    async def _hook_base(self) -> str:
        return (await self.public_url())[0]

    async def public_url(self) -> tuple[str, str]:
        """Return the base URL agents reach this server at, and where it comes from.

        In order: the ``PUBLIC_BASE_URL`` setting, a public URL saved from the UI
        (``setting``), an open tunnel (``tunnel``), then the address of the
        running server, or this process's own host and port (``local``). Saved
        values live in the database, so every process sharing it agrees.
        """
        if self.settings.public_base_url:
            return self.settings.public_base_url.rstrip("/"), "setting"
        if saved := await self.kv.get("public_base_url"):
            return saved.rstrip("/"), "setting"
        if tunnel := await self.kv.get("tunnel_url"):
            return tunnel.rstrip("/"), "tunnel"
        if serving := await self.kv.get("serve_url"):
            return serving, "local"
        return self._own_url(), "local"

    def _own_url(self) -> str:
        host = self.settings.host
        if host in ("0.0.0.0", "::", ""):
            host = "127.0.0.1"
        return f"http://{host}:{self.settings.port}"

    async def announce_serving(self) -> None:
        """Record this process's address as the running server's (``local`` webhook base)."""
        await self.kv.set("serve_url", self._own_url())

    async def set_public_url(self, url: str | None) -> None:
        """Save (or clear, with None) the public base URL agents should use."""
        await self.kv.set("public_base_url", (url or "").strip().rstrip("/") or None)

    async def set_tunnel_url(self, url: str | None) -> None:
        """Record (or clear) the URL of the open tunnel."""
        await self.kv.set("tunnel_url", url)

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
        if self.tunnel.running:
            await self.set_tunnel_url(None)
        await self.tunnel.stop()
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
