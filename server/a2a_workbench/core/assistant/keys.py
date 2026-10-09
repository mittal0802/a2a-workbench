"""Encrypted storage of LLM provider API keys, with environment-variable fallback."""

import os
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import delete, select

from a2a_workbench.core.assistant.llm import DEFAULT_MODELS, PROVIDERS
from a2a_workbench.core.auth.vault import Vault, VaultError
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import ProviderKey

ENV_VARS: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


class ProviderKeyInfo(BaseModel):
    """What may be shown about a provider key: never the key itself."""

    provider: str
    configured: bool
    source: Literal["stored", "env", "none"]
    preview: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    updated_at: datetime | None = None


def _preview(key: str) -> str:
    return f"••••{key[-4:]}" if len(key) >= 8 else "••••"


def _env_key(provider: str) -> str | None:
    for name in ENV_VARS.get(provider, ()):
        if os.environ.get(name):
            return os.environ[name]
    return None


class ProviderKeyStore:
    """One API key (and optional base URL) per provider, encrypted with the vault."""

    def __init__(self, db: Database, vault: Vault) -> None:
        self._db = db
        self._vault = vault

    @staticmethod
    def _check(provider: str) -> None:
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider '{provider}' (use one of {', '.join(PROVIDERS)})")

    async def put(
        self, provider: str, api_key: str, base_url: str | None = None
    ) -> ProviderKeyInfo:
        """Store (or replace) the key for ``provider``.

        Raises:
            ValueError: for an unknown provider or an empty key.
        """
        self._check(provider)
        if not api_key:
            raise ValueError("the API key is empty")
        blob = self._vault.encrypt({"api_key": api_key})
        async with self._db.sessions() as session:
            row = await session.get(ProviderKey, provider)
            if row is None:
                row = ProviderKey(provider=provider, encrypted=blob)
                session.add(row)
            row.encrypted, row.base_url = blob, base_url or None
            await session.commit()
            updated = row.updated_at
        return ProviderKeyInfo(
            provider=provider,
            configured=True,
            source="stored",
            preview=_preview(api_key),
            base_url=base_url or None,
            default_model=DEFAULT_MODELS.get(provider),
            updated_at=updated,
        )

    async def get(self, provider: str) -> tuple[str, str | None] | None:
        """Return ``(api_key, base_url)`` from storage, else the environment, else None."""
        self._check(provider)
        async with self._db.sessions() as session:
            row = await session.get(ProviderKey, provider)
        if row is not None:
            try:
                return str(self._vault.decrypt(row.encrypted)["api_key"]), row.base_url
            except VaultError:
                pass
        env = _env_key(provider)
        return (env, None) if env else None

    async def list(self) -> list[ProviderKeyInfo]:
        """Describe every provider: stored key, environment key, or none."""
        async with self._db.sessions() as session:
            rows = {r.provider: r for r in (await session.execute(select(ProviderKey))).scalars()}
        out = []
        for provider in PROVIDERS:
            row = rows.get(provider)
            info = ProviderKeyInfo(
                provider=provider,
                configured=False,
                source="none",
                default_model=DEFAULT_MODELS.get(provider),
            )
            if row is not None:
                try:
                    key = str(self._vault.decrypt(row.encrypted)["api_key"])
                    info = info.model_copy(
                        update={
                            "configured": True,
                            "source": "stored",
                            "preview": _preview(key),
                            "base_url": row.base_url,
                            "updated_at": row.updated_at,
                        }
                    )
                except VaultError:
                    pass
            if not info.configured and (env := _env_key(provider)):
                info = info.model_copy(
                    update={"configured": True, "source": "env", "preview": _preview(env)}
                )
            out.append(info)
        return out

    async def delete(self, provider: str) -> None:
        """Remove the stored key for ``provider`` (environment keys are untouched)."""
        self._check(provider)
        async with self._db.sessions() as session:
            await session.execute(delete(ProviderKey).where(ProviderKey.provider == provider))
            await session.commit()
