"""Async database engine, sessions and schema migrations."""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from a2a_workbench.core.store.models import Base

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
BASELINE = "0001"
_LOCK_ID = 0x0A2A0001  # Postgres advisory lock key held while migrating


def alembic_config(connection: Connection) -> Config:
    """An Alembic config that runs the packaged migrations on ``connection``."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection"] = connection
    return cfg


def head_revision() -> str | None:
    """The newest revision among the packaged migrations."""
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()


class Database:
    """Owns one async SQLAlchemy engine and a session factory bound to it.

    For SQLite file URLs the parent directory is created if missing, and
    connections wait up to 5 s for a lock (``busy_timeout``) instead of
    failing at once.
    """

    def __init__(self, url: str) -> None:
        parsed = make_url(url)
        self._url = url
        self._sqlite = parsed.get_backend_name() == "sqlite"
        if self._sqlite and parsed.database:
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_async_engine(url)
        if self._sqlite:
            event.listen(self.engine.sync_engine, "connect", _sqlite_busy_timeout)
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def migrate(self) -> None:
        """Bring the schema to the latest revision; safe to call on every start.

        Runs under a database-wide lock so concurrent processes migrate once.
        A database created before migrations existed (tables but no
        ``alembic_version``) is first completed to the current models,
        keeping its rows, and stamped.
        """
        engine = self.engine
        if self._sqlite:
            engine = create_async_engine(self._url, poolclass=NullPool)
            _sqlite_explicit_transactions(engine.sync_engine)
        try:
            async with engine.connect() as conn:
                await conn.run_sync(_migrate)
                await conn.commit()
        finally:
            if engine is not self.engine:
                await engine.dispose()

    async def revision(self) -> str | None:
        """The schema revision the database is at, or None before its first migration."""
        async with self.engine.connect() as conn:
            return await conn.run_sync(
                lambda c: MigrationContext.configure(c).get_current_revision()
            )

    async def dispose(self) -> None:
        """Close all pooled connections."""
        await self.engine.dispose()


def _sqlite_busy_timeout(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def _sqlite_explicit_transactions(engine: Any) -> None:
    # The SQLite driver opens transactions lazily and never for DDL; take over
    # BEGIN so a migration can hold the write lock from its first statement.
    @event.listens_for(engine, "connect")
    def _connect(dbapi_conn: Any, record: Any) -> None:
        _sqlite_busy_timeout(dbapi_conn, record)
        dbapi_conn.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin(conn: Connection) -> None:
        if not conn.info.pop("begun", False):
            conn.exec_driver_sql("BEGIN")


def _migrate(conn: Connection) -> None:
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql(f"SELECT pg_advisory_xact_lock({_LOCK_ID})")
    elif conn.dialect.name == "sqlite":
        conn.info["begun"] = True
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    cfg = alembic_config(conn)
    tables = set(inspect(conn).get_table_names())
    if "alembic_version" not in tables and "agent" in tables:
        Base.metadata.create_all(conn)
        _add_missing_columns(conn)
        command.stamp(cfg, "head")
    command.upgrade(cfg, "head")


def _add_missing_columns(conn: Connection) -> None:
    inspector = inspect(conn)
    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            column_type = column.type.compile(dialect=conn.dialect)
            conn.exec_driver_sql(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'
            )
