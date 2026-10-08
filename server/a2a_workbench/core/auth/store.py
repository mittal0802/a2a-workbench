"""Encrypted per-agent credentials, one per security scheme."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import delete, select

from a2a_workbench.core.auth.vault import Vault, VaultError
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import Credential

CredentialKind = Literal["api_key", "http_basic", "http_bearer", "oauth2", "mtls"]


class CredentialInfo(BaseModel):
    """What may be shown about a stored credential: never the secret itself."""

    scheme_name: str
    kind: str
    preview: str
    readable: bool
    expires_at: datetime | None
    updated_at: datetime


def _tail(value: str) -> str:
    return f"••••{value[-4:]}" if len(value) >= 8 else "••••"


def preview(kind: str, secret: dict[str, Any]) -> str:
    """Return a masked, human-readable summary of a credential."""
    if kind == "api_key":
        return _tail(str(secret.get("value", "")))
    if kind == "http_basic":
        return f"{secret.get('username', '')} · ••••"
    if kind == "http_bearer":
        return _tail(str(secret.get("token", "")))
    if kind == "oauth2":
        scopes = " ".join(secret.get("scopes") or [])
        signed_in = "signed in" if secret.get("access_token") else "not signed in"
        return f"{signed_in}{' · ' + scopes if scopes else ''}"
    if kind == "mtls":
        return "client certificate"
    return "••••"


class CredentialStore:
    """Stores credentials encrypted with the vault, keyed by agent and scheme name."""

    def __init__(self, db: Database, vault: Vault) -> None:
        self._db = db
        self._vault = vault

    async def put(
        self,
        agent_id: str,
        scheme_name: str,
        kind: CredentialKind,
        secret: dict[str, Any],
        *,
        expires_at: datetime | None = None,
    ) -> CredentialInfo:
        """Store (or replace) the credential for ``scheme_name`` of an agent."""
        blob = self._vault.encrypt(secret)
        async with self._db.sessions() as session:
            row = (
                await session.execute(
                    select(Credential).where(
                        Credential.agent_id == agent_id, Credential.scheme_name == scheme_name
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = Credential(
                    agent_id=agent_id, scheme_name=scheme_name, kind=kind, encrypted=blob
                )
                session.add(row)
            row.kind, row.encrypted, row.expires_at = kind, blob, expires_at
            await session.commit()
            return CredentialInfo(
                scheme_name=scheme_name,
                kind=kind,
                preview=preview(kind, secret),
                readable=True,
                expires_at=expires_at,
                updated_at=row.updated_at,
            )

    async def _rows(self, agent_id: str) -> list[Credential]:
        async with self._db.sessions() as session:
            result = await session.execute(
                select(Credential)
                .where(Credential.agent_id == agent_id)
                .order_by(Credential.scheme_name)
            )
            return list(result.scalars().all())

    async def get(self, agent_id: str, scheme_name: str) -> dict[str, Any] | None:
        """Return the decrypted credential, or None if missing or unreadable."""
        for row in await self._rows(agent_id):
            if row.scheme_name == scheme_name:
                try:
                    return self._vault.decrypt(row.encrypted)
                except VaultError:
                    return None
        return None

    async def all(self, agent_id: str) -> dict[str, dict[str, Any]]:
        """Return every readable credential of an agent, by scheme name, with its kind."""
        out: dict[str, dict[str, Any]] = {}
        for row in await self._rows(agent_id):
            try:
                out[row.scheme_name] = {"kind": row.kind, **self._vault.decrypt(row.encrypted)}
            except VaultError:
                continue
        return out

    async def list(self, agent_id: str) -> list[CredentialInfo]:
        """Describe every stored credential of an agent without revealing secrets."""
        infos = []
        for row in await self._rows(agent_id):
            try:
                text, readable = preview(row.kind, self._vault.decrypt(row.encrypted)), True
            except VaultError:
                text, readable = "cannot be read — enter it again", False
            infos.append(
                CredentialInfo(
                    scheme_name=row.scheme_name,
                    kind=row.kind,
                    preview=text,
                    readable=readable,
                    expires_at=row.expires_at,
                    updated_at=row.updated_at,
                )
            )
        return infos

    async def delete(self, agent_id: str, scheme_name: str) -> None:
        """Remove the credential for ``scheme_name`` of an agent, if any."""
        async with self._db.sessions() as session:
            await session.execute(
                delete(Credential).where(
                    Credential.agent_id == agent_id, Credential.scheme_name == scheme_name
                )
            )
            await session.commit()

    async def delete_agent(self, agent_id: str) -> None:
        """Remove every credential of an agent."""
        async with self._db.sessions() as session:
            await session.execute(delete(Credential).where(Credential.agent_id == agent_id))
            await session.commit()
