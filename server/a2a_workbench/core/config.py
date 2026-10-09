"""Runtime configuration."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration read from ``A2AW_*`` environment variables.

    ``database_url`` also accepts the conventional unprefixed ``DATABASE_URL``.
    """

    model_config = SettingsConfigDict(env_prefix="A2AW_", extra="ignore", populate_by_name=True)

    home: Path = Field(default_factory=lambda: Path.home() / ".a2a-workbench")
    database_url: str | None = Field(
        default=None, validation_alias=AliasChoices("A2AW_DATABASE_URL", "DATABASE_URL")
    )
    host: str = "127.0.0.1"
    port: int = 8484
    mode: Literal["local", "hosted"] = "local"
    max_blob_bytes: int = 20 * 1024 * 1024
    max_recorded_body_bytes: int = 1024 * 1024
    allowed_hosts: str = ""
    secret_key: str | None = None

    @property
    def extra_allowed_hosts(self) -> list[str]:
        """Hostnames from the comma-separated ``allowed_hosts`` setting."""
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def resolved_database_url(self) -> str:
        """Return the configured database URL, or a SQLite file inside ``home``."""
        return self.database_url or f"sqlite+aiosqlite:///{self.home / 'workbench.db'}"
