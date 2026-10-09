"""Workbench webhooks: one URL and single-purpose credentials per push config."""

import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import delete, select

from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import PushHook


def digest(value: str) -> str:
    """SHA-256 hex digest of ``value`` (how hook secrets are stored)."""
    return hashlib.sha256(value.encode()).hexdigest()


class NewHook(BaseModel):
    """A freshly created hook, including its secrets (returned only once)."""

    id: str
    agent_id: str
    url: str
    token: str
    auth_scheme: str
    credentials: str
    task_id: str | None
    conversation_id: str | None


class HookOut(BaseModel):
    """A hook as shown later: no secrets."""

    id: str
    agent_id: str
    url: str
    auth_scheme: str
    task_id: str | None
    conversation_id: str | None
    created_at: datetime


class HookStore:
    """Creates and looks up webhooks; secrets are stored only as hashes."""

    def __init__(self, db: Database, base_url: Callable[[], str]) -> None:
        self._db = db
        self._base_url = base_url

    def url_for(self, hook_id: str) -> str:
        """The URL an agent POSTs notifications to for ``hook_id``."""
        return f"{self._base_url().rstrip('/')}/hooks/{hook_id}"

    async def create(
        self, agent_id: str, *, task_id: str | None = None, conversation_id: str | None = None
    ) -> NewHook:
        """Create a hook with a new token and Bearer credential (A2A §13.2: single-purpose)."""
        token, credentials = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        row = PushHook(
            agent_id=agent_id,
            task_id=task_id,
            conversation_id=conversation_id,
            auth_scheme="Bearer",
            credentials_hash=digest(credentials),
            token_hash=digest(token),
        )
        async with self._db.sessions() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return NewHook(
            id=row.id,
            agent_id=agent_id,
            url=self.url_for(row.id),
            token=token,
            auth_scheme="Bearer",
            credentials=credentials,
            task_id=task_id,
            conversation_id=conversation_id,
        )

    def _out(self, row: PushHook) -> HookOut:
        return HookOut(
            id=row.id,
            agent_id=row.agent_id,
            url=self.url_for(row.id),
            auth_scheme=row.auth_scheme,
            task_id=row.task_id,
            conversation_id=row.conversation_id,
            created_at=row.created_at,
        )

    async def row(self, hook_id: str) -> PushHook | None:
        """Return the stored hook, or None."""
        async with self._db.sessions() as session:
            return await session.get(PushHook, hook_id)

    async def get(self, hook_id: str) -> HookOut | None:
        """Return the hook without secrets, or None."""
        row = await self.row(hook_id)
        return self._out(row) if row else None

    async def list(self, agent_id: str) -> list[HookOut]:
        """Return the agent's hooks, newest first."""
        async with self._db.sessions() as session:
            rows = (
                await session.execute(
                    select(PushHook)
                    .where(PushHook.agent_id == agent_id)
                    .order_by(PushHook.created_at.desc())
                )
            ).scalars()
            return [self._out(r) for r in rows]

    async def bind_task(self, hook_id: str, task_id: str) -> None:
        """Set the task a hook expects, if it has none yet."""
        async with self._db.sessions() as session:
            row = await session.get(PushHook, hook_id)
            if row is not None and row.task_id is None:
                row.task_id = task_id
                await session.commit()

    async def delete(self, hook_id: str) -> None:
        """Delete the hook (later deliveries to it answer 404)."""
        async with self._db.sessions() as session:
            await session.execute(delete(PushHook).where(PushHook.id == hook_id))
            await session.commit()
