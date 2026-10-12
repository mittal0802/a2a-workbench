"""Runtime configuration."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration read from ``A2AW_*`` environment variables.

    ``database_url`` also accepts the conventional unprefixed ``DATABASE_URL`` and
    ``public_base_url`` the unprefixed ``PUBLIC_BASE_URL``.
    """

    model_config = SettingsConfigDict(env_prefix="A2AW_", extra="ignore", populate_by_name=True)

    home: Path = Field(
        default_factory=lambda: Path.home() / ".a2a-workbench",
        description="Directory for the SQLite database, the secret key and uploaded files.",
    )
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("A2AW_DATABASE_URL", "DATABASE_URL"),
        description="SQLAlchemy URL of the database; default a SQLite file in the home "
        "directory. Postgres: `postgresql+asyncpg://user:password@host/db` (needs the "
        "`postgres` extra). Also read from `DATABASE_URL`.",
    )
    host: str = Field(default="127.0.0.1", description="Address `serve` binds to.")
    port: int = Field(default=8484, description="Port `serve` listens on.")
    mode: Literal["local", "hosted"] = Field(
        default="local", json_schema_extra={"undocumented": True}
    )
    max_blob_bytes: int = Field(
        default=20 * 1024 * 1024, description="Largest file you can upload to attach to a message."
    )
    max_recorded_body_bytes: int = Field(
        default=1024 * 1024, json_schema_extra={"undocumented": True}
    )
    allowed_hosts: str = Field(
        default="",
        description="Extra comma-separated host names the server answers to besides "
        "localhost and its bind address (DNS-rebinding protection).",
    )
    secret_key: str | None = Field(
        default=None,
        description="Key that encrypts stored credentials; default a key generated in "
        "`<home>/secret.key`.",
    )
    public_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("A2AW_PUBLIC_BASE_URL", "PUBLIC_BASE_URL"),
        description="Base URL agents use to reach this server's push webhooks "
        "(`/hooks/<id>`). Also read from `PUBLIC_BASE_URL`.",
    )

    @property
    def extra_allowed_hosts(self) -> list[str]:
        """Hostnames from the comma-separated ``allowed_hosts`` setting."""
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def resolved_database_url(self) -> str:
        """Return the configured database URL, or a SQLite file inside ``home``."""
        return self.database_url or f"sqlite+aiosqlite:///{self.home / 'workbench.db'}"
