"""Small persistent settings shared by every process using the same state directory."""

from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import WorkbenchSetting


class SettingsStore:
    """String values by key, stored in the database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str) -> str | None:
        """Return the value for ``key``, or None."""
        async with self._db.sessions() as session:
            row = await session.get(WorkbenchSetting, key)
            return row.value if row else None

    async def set(self, key: str, value: str | None) -> None:
        """Store ``value`` for ``key``; None deletes it."""
        async with self._db.sessions() as session:
            row = await session.get(WorkbenchSetting, key)
            if value is None:
                if row is not None:
                    await session.delete(row)
            elif row is None:
                session.add(WorkbenchSetting(key=key, value=value))
            else:
                row.value = value
            await session.commit()
