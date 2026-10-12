# Phase 7a — Migrations, Postgres, docs site and the v1.0.0 release: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make A2A Workbench installable and operable by strangers: versioned schema migrations (Alembic) that also upgrade pre-1.0 databases, Postgres as a supported database, a docs site on GitHub Pages, and a tag-driven release that publishes the wheel to PyPI and a multi-arch image to GHCR as v1.0.0.

**Architecture:** `core/store/migrations/` is an Alembic environment shipped inside the package; `Database.migrate()` runs it programmatically on startup under a database-wide lock (Postgres advisory lock, SQLite `BEGIN IMMEDIATE`), stamping pre-1.0 databases first. Postgres support is the `postgres` extra (`asyncpg`) and a CI job that runs the store, migration and lifecycle tests against a Postgres service. The version has one source (`a2a_workbench.__version__`), read by hatch, the CLI `--version`, the API and the release workflow. A `release.yml` workflow on `v*` tags reuses CI, builds wheel and sdist with the SPA inside, smoke-installs the wheel, publishes to PyPI through trusted publishing (no tokens), pushes `ghcr.io/mittal0802/a2a-workbench` for amd64 and arm64, and creates the GitHub release from `CHANGELOG.md`. The docs site is MkDocs Material built from `docs/` (internal folders excluded), with the health-check catalogue and CLI reference generated from code and guarded by up-to-date tests.

**Tech Stack:** Alembic, SQLAlchemy 2 async, asyncpg, aiosqlite, hatchling, GitHub Actions (pypa/gh-action-pypi-publish, docker/build-push-action, actions/deploy-pages), MkDocs Material, Typer.

**Spec:** `docs/superpowers/specs/2026-10-07-a2a-workbench-design.md` §8 (hosted instance runs on Postgres), §11 storage note ("Alembic migrations arrive in Phase 7, before the first public release"), §12 Phase 7. Phase 7 is split by the maintainer's decision (2026-10-12): **7a** = this plan; **7b** = hosted mode (GitHub OAuth sign-in, per-user workspaces, SSRF guard, rate limits, probe concurrency limits), planned separately.

## Global Constraints

- Earlier constraints apply: A2A traffic only through the official SDK; secrets never logged; docstrings describe the function; every feature on every surface.
- **No AI attribution anywhere**: commits, tags, release notes, CHANGELOG, workflow names, docs. The release body comes only from `CHANGELOG.md`.
- **Identity**: commits as `Keshav Mittal <mittalkeshav41@gmail.com>`; push only to `mittal0802`. Never `--no-verify`.
- **Outward actions need the maintainer's go-ahead at the moment they happen**: making the repo public, configuring the PyPI trusted publisher, enabling GitHub Pages, pushing the `v1.0.0` tag. The plan prepares everything; Task 7 stops before the tag.
- Version `1.0.0`. After 1.0 the stable surface is: CLI commands, flags and exit codes; report JSON schema `1`; REST paths under `/api`; MCP tool names and arguments. Breaking any of them needs a major version.
- Python `>=3.12`; image based on `python:3.13-slim`; Postgres 15+ supported (CI uses 16).
- No secrets in workflows: PyPI via OIDC trusted publishing, GHCR via `GITHUB_TOKEN`.

## Review Focus

1. **Upgrading an existing 0.1 database loses nothing.** A user's `~/.a2a-workbench/workbench.db` created by `create_all` (with or without later-added columns) must open under 1.0 with all rows intact and be stamped at head. *Test:* Task 1 `test_legacy_database_is_upgraded_in_place`.
2. **Two processes starting at once on the same fresh database** (e.g. `serve` and a CLI command, or two replicas on Postgres) must both start; neither may fail with "table already exists". *Test:* Task 1 `test_concurrent_migrate_on_sqlite`, Task 2 `test_concurrent_migrate_on_postgres`.
3. **Values from agents longer than a column bound** (a 300-char task id, a 600-char agent name, a 5 000-char error) are stored on Postgres, which enforces `VARCHAR(n)` where SQLite silently does not. *Test:* Task 2 `test_long_external_values_on_postgres` and `test_bounded_columns_hold_only_internal_values`.
4. **A wheel without the web UI or without the migration scripts** installs fine and then serves a blank page or crashes on first start. *Test:* Task 3 `test_wheel_contents` and the release workflow's smoke install.
5. **The image runs as non-root but `/data` is a volume**: first start on an empty named volume must be able to write the database and the secret key. *Test:* Task 4 docker smoke step (`docker run -v a2aw-data:/data …` then `GET /api/health`).

---

### Task 1: Alembic migrations with an upgrade path for pre-1.0 databases

**Files:**
- Create: `server/a2a_workbench/core/store/migrations/__init__.py`, `env.py`, `script.py.mako`, `versions/0001_baseline.py`
- Modify: `server/a2a_workbench/core/store/db.py` (replace `create_schema` with `migrate`), `server/a2a_workbench/core/workbench.py:99`, every test that calls `create_schema` (`tests/core/test_db.py`, `test_exchanges.py`, `test_schema_upgrade.py`)
- Modify: `server/pyproject.toml` (add `alembic>=1.14`)
- Test: `server/tests/core/store/test_migrations.py`

**Interfaces:**
- Produces: `Database.migrate() -> None` (idempotent; brings any database to head); `MIGRATIONS_DIR: Path`; `BASELINE = "0001"`; `alembic_config(connection) -> alembic.config.Config`. Task 2 consumes all of these.

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/core/store/test_migrations.py
import asyncio
import sqlite3

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import Base


def _url(path):
    return f"sqlite+aiosqlite:///{path}"


async def _diff(db):
    async with db.engine.connect() as conn:
        return await conn.run_sync(
            lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata)
        )


async def test_fresh_database_matches_models(tmp_path):
    db = Database(_url(tmp_path / "a.db"))
    await db.migrate()
    assert await _diff(db) == []
    await db.dispose()


async def test_migrate_is_idempotent(tmp_path):
    db = Database(_url(tmp_path / "a.db"))
    await db.migrate()
    await db.migrate()
    async with db.engine.connect() as conn:
        rev = (await conn.execute(text("select version_num from alembic_version"))).scalar_one()
    assert rev == "0001"
    await db.dispose()


async def test_legacy_database_is_upgraded_in_place(tmp_path):
    path = tmp_path / "legacy.db"
    legacy = Database(_url(path))
    async with legacy.engine.begin() as conn:  # a 0.1 database: create_all, one column missing
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("ALTER TABLE agent DROP COLUMN selected_interface_url")
        await conn.exec_driver_sql("INSERT INTO workspace (id, name) VALUES ('w1', 'Old')")
    await legacy.dispose()

    db = Database(_url(path))
    await db.migrate()
    assert await _diff(db) == []
    async with db.engine.connect() as conn:
        names = (await conn.execute(text("select name from workspace where id='w1'"))).all()
    assert names == [("Old",)]
    await db.dispose()


async def test_concurrent_migrate_on_sqlite(tmp_path):
    path = tmp_path / "race.db"
    dbs = [Database(_url(path)) for _ in range(4)]
    await asyncio.gather(*(d.migrate() for d in dbs))
    assert sqlite3.connect(path).execute("select count(*) from alembic_version").fetchone() == (1,)
    for d in dbs:
        await d.dispose()
```


- [ ] **Step 2: Run to verify they fail**

Run: `cd server && uv run pytest tests/core/store/test_migrations.py -q`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'migrate'`.

- [ ] **Step 3: Add the Alembic environment**

`uv add 'alembic>=1.14'`. Generate the baseline from the current models with `alembic revision --autogenerate` against an empty SQLite file, rename it to `versions/0001_baseline.py` with `revision = "0001"`, `down_revision = None`, and review it by hand (every table, index and column type from `models.py`, nothing else). `env.py` runs only online, on the connection passed in `config.attributes["connection"]`:

```python
# server/a2a_workbench/core/store/migrations/env.py
"""Alembic environment: migrates the connection handed over in ``config.attributes``."""

from alembic import context

from a2a_workbench.core.store.models import Base

connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=connection.dialect.name == "sqlite",
)
with context.begin_transaction():
    context.run_migrations()
```

`render_as_batch` lets later migrations alter SQLite tables (SQLite has no `ALTER COLUMN`).

- [ ] **Step 4: Implement `Database.migrate`**

```python
# server/a2a_workbench/core/store/db.py  (replaces create_schema)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
BASELINE = "0001"
_LOCK_ID = 0x0A2A_0001  # Postgres advisory lock key for schema migrations


def alembic_config(connection: Connection) -> Config:
    """An Alembic config that runs the packaged migrations on ``connection``."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection"] = connection
    return cfg


class Database:
    ...
    async def migrate(self) -> None:
        """Bring the schema to the latest revision; safe to call on every start.

        Runs under a database-wide lock so concurrent processes migrate once.
        A database created before migrations existed (tables but no
        ``alembic_version``) is first completed to the baseline schema, keeping
        its rows, and stamped.
        """
        async with self.engine.connect() as conn:
            await conn.run_sync(_migrate)
            await conn.commit()


def _migrate(conn: Connection) -> None:
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql(f"SELECT pg_advisory_xact_lock({_LOCK_ID})")
    elif conn.dialect.name == "sqlite":
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    cfg = alembic_config(conn)
    tables = set(inspect(conn).get_table_names())
    if "alembic_version" not in tables and "agent" in tables:
        Base.metadata.create_all(conn)
        _add_missing_columns(conn)
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")
```

SQLite needs SQLAlchemy to stop emitting its own `BEGIN` so `BEGIN IMMEDIATE` takes effect: in `Database.__init__`, for SQLite, set `isolation_level=None` on the driver connection via `event.listens_for(self.engine.sync_engine, "connect")` and emit `BEGIN` from a `"begin"` listener (the documented pysqlite recipe in SQLAlchemy's SQLite dialect docs, "Serializable isolation / Savepoints / Transactional DDL"), skipping the extra `BEGIN` when one is already open. Also set `PRAGMA busy_timeout=5000` and `PRAGMA journal_mode=WAL` in the connect listener — this fixes the deferred "database is locked" minor from Phase 6. If the recipe and Alembic's own transaction handling conflict, rule on the smallest working variant and ledger it; the concurrency test is the arbiter.

Replace `create_schema()` with `migrate()` at `workbench.py:99` and in the tests listed above; keep `_add_missing_columns` (used only for legacy databases).

- [ ] **Step 5: Run to verify they pass, then the suite**

Run: `cd server && uv run pytest tests/core/store/test_migrations.py -q && uv run pytest -q`
Expected: 4 passed; full suite green.

- [ ] **Step 6: Add `a2a-workbench db` commands (every surface)**

CLI: `a2a-workbench db upgrade` (runs `migrate`, prints the revision) and `a2a-workbench db current [--json]` (prints `{"revision": "0001", "head": "0001", "database": "<url with password masked>"}`), exit 0. Test in `tests/cli/test_db_cli.py` with `CliRunner` on a temp home: `current` on a fresh home prints `"revision": null`, then `upgrade`, then `current` prints `"0001"`. No API or MCP surface: schema management is an operator task, not a user feature — record that ruling in the ledger.

- [ ] **Step 7: Commit**

```bash
git add server/ && git commit -m "feat(store): Alembic migrations with in-place upgrade of pre-1.0 databases"
```

---

### Task 2: Postgres as a supported database

**Files:**
- Modify: `server/pyproject.toml` (extra `postgres = ["asyncpg>=0.30"]`), `server/a2a_workbench/core/store/models.py` (widen external-value columns), `server/a2a_workbench/core/store/migrations/versions/0001_baseline.py` (regenerate — nothing is released yet, so the baseline absorbs this)
- Modify: `.github/workflows/ci.yml` (`server-postgres` job)
- Test: `server/tests/core/store/conftest.py`, `test_postgres.py`, `test_columns.py`

**Interfaces:**
- Consumes: `Database.migrate`, `BASELINE` from Task 1.
- Produces: pytest fixture `pg_url` (skips unless `A2AW_TEST_POSTGRES_URL` is set; yields a URL to a fresh database per test); CI job name `server-postgres`.

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/core/store/test_columns.py
from sqlalchemy import String

from a2a_workbench.core.store.models import Base

# Bounded columns may only hold values the Workbench generates itself.
INTERNAL = {"id", "workspace_id", "agent_id", "conversation_id", "exchange_id", "kind",
            "status", "origin", "provider", "response_mode", "signature_status",
            "credentials_hash", "auth_scheme", "task_state"}


def test_bounded_columns_hold_only_internal_values():
    offenders = [
        f"{t.name}.{c.name}"
        for t in Base.metadata.sorted_tables
        for c in t.columns
        if isinstance(c.type, String) and c.type.length and c.name not in INTERNAL
    ]
    assert offenders == []
```

```python
# server/tests/core/store/conftest.py
import os
import uuid

import asyncpg
import pytest
from sqlalchemy.engine import make_url


@pytest.fixture
async def pg_url():
    """A SQLAlchemy URL to a new, empty Postgres database, dropped afterwards."""
    base = os.environ.get("A2AW_TEST_POSTGRES_URL")
    if not base:
        pytest.skip("A2AW_TEST_POSTGRES_URL not set")
    url = make_url(base)
    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    name = f"t_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(dsn)
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()
```

```python
# server/tests/core/store/test_postgres.py
import asyncio

from sqlalchemy import select, text

from a2a_workbench.core.config import Settings
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import Agent, ExchangeRow, TimelineEventRow
from a2a_workbench.core.workbench import Workbench

from .test_migrations import _diff


async def test_fresh_postgres_matches_models(pg_url):
    db = Database(pg_url)
    await db.migrate()
    assert await _diff(db) == []
    await db.dispose()


async def test_concurrent_migrate_on_postgres(pg_url):
    dbs = [Database(pg_url) for _ in range(4)]
    await asyncio.gather(*(d.migrate() for d in dbs))
    async with dbs[0].engine.connect() as conn:
        rows = (await conn.execute(text("select version_num from alembic_version"))).all()
    assert rows == [("0001",)]
    for d in dbs:
        await d.dispose()


async def test_long_external_values_on_postgres(pg_url):
    db = Database(pg_url)
    await db.migrate()
    name, task_id, error = "n" * 600, "t" * 300, "e" * 5000
    async with db.sessions() as s:
        # Fill the remaining required columns from models.py when writing this.
        agent = Agent(name=name, base_url="http://x/" + "p" * 3000, card={}, signature_status="unsigned")
        s.add(agent)
        await s.flush()
        s.add(TimelineEventRow(conversation_id="c" * 32, seq=1, kind="task", task_id=task_id, data={}))
        s.add(ExchangeRow(agent_id=agent.id, operation="send_message", error=error, started_at=agent.created_at))
        await s.commit()
    async with db.sessions() as s:
        assert (await s.scalar(select(Agent.name))) == name
        assert (await s.scalar(select(TimelineEventRow.task_id))) == task_id
        assert (await s.scalar(select(ExchangeRow.error))) == error
    await db.dispose()


async def test_workbench_lifecycle_on_postgres(pg_url, zoo):
    async with Workbench.open(Settings(database_url=pg_url)) as wb:
        agent = await wb.agents.add(zoo.base_url)
        conv = await wb.conversations.create(agent.id)
        events = [e async for e in wb.conversations.send(conv.id, [TextPartInput(text="hi")], SendOptions())]
        assert events[-1].kind == "status" and events[-1].data["state"] == "completed"
        progress = [e async for e in wb.health.run(agent.id, areas=["A"])]
        run = await wb.health.get(progress[0].run_id)
        assert run.status == "done" and run.results
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd server && uv run pytest tests/core/store/test_columns.py -q`
Expected: FAIL listing `agent.name`, `agent.base_url`, `conversation.task_id`, `exchange.error`, … .
Run (with a local Postgres, e.g. `docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=pw postgres:16`): `A2AW_TEST_POSTGRES_URL=postgresql+asyncpg://postgres:pw@localhost/postgres uv run pytest tests/core/store -q`
Expected: FAIL — `ModuleNotFoundError: asyncpg`; after adding it, `StringDataRightTruncationError` in `test_long_external_values_on_postgres`.

- [ ] **Step 3: Implement**

`uv add --optional postgres 'asyncpg>=0.30'` and add `asyncpg` to the dev group so tests import it. In `models.py` change every non-`INTERNAL` `String(n)` to `String()` (unbounded `VARCHAR` on Postgres, `TEXT` affinity on SQLite). Regenerate `0001_baseline.py` and review the diff. If `Database` or any service uses SQLite-only SQL, make it portable and ledger each change.

- [ ] **Step 4: CI job**

```yaml
  server-postgres:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_PASSWORD: pw }
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 5s --health-timeout 5s --health-retries 10
    defaults: { run: { working-directory: server } }
    env:
      A2AW_TEST_POSTGRES_URL: postgresql+asyncpg://postgres:pw@localhost:5432/postgres
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --python 3.13 --extra postgres
      - run: uv run pytest tests/core/store -q
```

- [ ] **Step 5: Run to verify they pass**

Run: the two commands from Step 2.
Expected: all pass; then `uv run pytest -q` green.

- [ ] **Step 6: Commit**

```bash
git add server/ .github/ && git commit -m "feat(store): support Postgres through the postgres extra"
```

---

### Task 3: One version, `--version`, and a complete wheel

**Files:**
- Modify: `server/pyproject.toml` (`dynamic = ["version"]`, `[tool.hatch.version] path = "a2a_workbench/__init__.py"`, classifiers, `[project.urls]`, `[project.optional-dependencies]` from Task 2), `server/a2a_workbench/__init__.py` (`__version__ = "1.0.0"`), `server/a2a_workbench/cli/main.py` (`--version`), `server/README.md` (PyPI page: install, run, links)
- Test: `server/tests/cli/test_version.py`, `server/tests/test_wheel.py`

**Interfaces:**
- Produces: `a2a-workbench --version` prints `a2a-workbench 1.0.0`; `scripts/check-version.sh <tag>` exits non-zero unless `<tag>` == `v` + `__version__` (Task 5 consumes).

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/cli/test_version.py
from typer.testing import CliRunner

from a2a_workbench import __version__
from a2a_workbench.cli.main import app


def test_version_flag():
    out = CliRunner().invoke(app, ["--version"])
    assert out.exit_code == 0
    assert out.stdout.strip() == f"a2a-workbench {__version__}"
```

```python
# server/tests/test_wheel.py
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (ROOT / "a2a_workbench/static/index.html").exists(), reason="SPA not built")
def test_wheel_contents(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "-o", str(tmp_path)], cwd=ROOT, check=True)
    (wheel,) = tmp_path.glob("a2a_workbench-*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    assert "a2a_workbench/static/index.html" in names
    assert "a2a_workbench/core/store/migrations/env.py" in names
    assert "a2a_workbench/core/store/migrations/script.py.mako" in names
    assert any(n.startswith("a2a_workbench/core/store/migrations/versions/0001") for n in names)
```

Also a test that `scripts/check-version.sh v1.0.0` exits 0 and `v1.0.1` exits 1.

- [ ] **Step 2: Run to verify they fail**

Run: `cd server && uv run pytest tests/cli/test_version.py tests/test_wheel.py -q`
Expected: `test_version_flag` FAIL (no such option); `test_wheel_contents` FAIL on `script.py.mako` (hatch includes only `.py` under `packages` plus `artifacts`), or skip when the SPA is not built — run `scripts/build.sh --no-wheel` first so it runs.

- [ ] **Step 3: Implement**

Typer callback with `--version` (eager, `is_eager=True`). In `pyproject.toml`: dynamic version, `artifacts` gains `"a2a_workbench/core/store/migrations/**"`, classifiers (`Development Status :: 5 - Production/Stable`, `License :: OSI Approved :: Apache Software License`, `Programming Language :: Python :: 3.12/3.13`, `Topic :: Software Development :: Testing`, `Framework :: FastAPI`), `[project.urls]` Homepage = docs site, Repository, Issues, Changelog. `scripts/check-version.sh`:

```bash
#!/usr/bin/env bash
# Exits 0 when the tag (e.g. v1.0.0) matches the package version.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$root/server/a2a_workbench/__init__.py")"
[ "$1" = "v$version" ] || { echo "tag $1 does not match version $version" >&2; exit 1; }
```

- [ ] **Step 4: Run to verify they pass, then the suite**

Run: `cd server && uv run pytest -q`
Expected: green, including both new tests.

- [ ] **Step 5: Commit**

```bash
git add server/ scripts/ && git commit -m "feat: single-source version 1.0.0, --version, complete wheel"
```

---

### Task 4: Production Docker image

**Files:**
- Modify: `Dockerfile`, `.github/workflows/ci.yml` (`docker` job gains a smoke run)
- Create: `docker-compose.yml` (Workbench + Postgres example), `.dockerignore`

**Interfaces:**
- Produces: image that runs as UID 10001, listens on 8484, stores state in `/data`, includes the `postgres` extra, has a `HEALTHCHECK` on `/api/health`, and OCI labels (`org.opencontainers.image.source=https://github.com/mittal0802/a2a-workbench`, `.licenses=Apache-2.0`, `.version`). Task 5 builds it for `linux/amd64,linux/arm64`.

- [ ] **Step 1: Write the failing smoke step** in the CI `docker` job and run the same commands locally:

```bash
docker build -t a2a-workbench:ci .
docker volume create a2aw-data
docker run -d --name a2aw -p 8484:8484 -v a2aw-data:/data a2a-workbench:ci
for i in $(seq 1 30); do curl -fs localhost:8484/api/health && break; sleep 1; done
curl -fs localhost:8484/api/health | grep '"version":"1.0.0"'
curl -fs localhost:8484/ | grep -q '<div id="root">'
test "$(docker exec a2aw id -u)" = 10001
docker exec a2aw a2a-workbench db current --json | grep '"revision": "0001"'
```

Expected now: FAIL at `id -u` (the image runs as root) — and `.dockerignore` is missing, so `server/.venv` and `web/node_modules` are sent to the build.

- [ ] **Step 2: Implement**

Pin the uv image to a version tag instead of `latest`. Install with `uv pip install --system --no-cache ".[postgres]"`. Create the user and the data directory before `VOLUME` so a new named volume inherits ownership:

```dockerfile
RUN useradd --uid 10001 --create-home workbench && mkdir /data && chown workbench /data
USER workbench
ENV A2AW_HOST=0.0.0.0 A2AW_HOME=/data
VOLUME /data
EXPOSE 8484
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8484/api/health'); sys.exit(0)"
```

`.dockerignore`: `**/.venv`, `**/node_modules`, `**/__pycache__`, `server/dist`, `server/a2a_workbench/static`, `web/dist`, `.git`, `.superpowers`. `docker-compose.yml`: `postgres:16` with a volume and `A2AW_DATABASE_URL=postgresql+asyncpg://…`, Workbench depending on its healthcheck; the password comes from an `.env` file, never inline.

- [ ] **Step 3: Run the smoke commands** — Expected: every command succeeds. Then `docker compose up -d` and the same `curl` and `db current` checks against the Postgres-backed instance.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml .github/ && git commit -m "feat(docker): non-root image with Postgres support, healthcheck and compose example"
```

---

### Task 5: Tag-driven release workflow

**Files:**
- Create: `.github/workflows/release.yml`, `CHANGELOG.md`, `scripts/release-notes.sh`
- Modify: `.github/workflows/ci.yml` (add `on: workflow_call` so release reuses it)
- Test: `server/tests/test_release_notes.py`

**Interfaces:**
- Consumes: `scripts/check-version.sh` (Task 3), the image (Task 4), `scripts/build.sh`.
- Produces: `scripts/release-notes.sh <version>` prints that version's `CHANGELOG.md` section body; fails if it is missing or empty.

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_release_notes.py
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(version, changelog, tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    return subprocess.run([str(ROOT / "scripts/release-notes.sh"), version, str(tmp_path / "CHANGELOG.md")],
                          capture_output=True, text=True)


def test_prints_only_that_section(tmp_path):
    out = run("1.0.0", "# Changelog\n\n## 1.0.0 — 2026-10-20\n\n- First release.\n\n## 0.1.0\n\n- Old.\n", tmp_path)
    assert out.returncode == 0
    assert out.stdout.strip() == "- First release."


def test_missing_section_fails(tmp_path):
    assert run("1.0.1", "# Changelog\n\n## 1.0.0\n\n- x\n", tmp_path).returncode == 1
```

- [ ] **Step 2: Run** `cd server && uv run pytest tests/test_release_notes.py -q` — Expected: FAIL (script missing).

- [ ] **Step 3: Implement** `scripts/release-notes.sh` (awk between `## <version>` and the next `## `; exit 1 if empty) and `CHANGELOG.md` with a `## 1.0.0` section summarising phases 1–7a in user terms. Then `release.yml`:

```yaml
name: Release
on:
  push:
    tags: ["v*"]
permissions: { contents: read }
jobs:
  ci:
    uses: ./.github/workflows/ci.yml
  build:
    needs: ci
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: scripts/check-version.sh "${GITHUB_REF_NAME}"
      - uses: astral-sh/setup-uv@v6
      - uses: pnpm/action-setup@v4
        with: { package_json_file: web/package.json }
      - uses: actions/setup-node@v5
        with: { node-version: 22 }
      - run: scripts/build.sh
      - name: Smoke-install the wheel
        run: |
          uv venv /tmp/smoke && . /tmp/smoke/bin/activate
          uv pip install server/dist/*.whl
          a2a-workbench --version | grep "${GITHUB_REF_NAME#v}"
          A2AW_HOME=/tmp/smoke-home a2a-workbench serve --port 8599 & 
          for i in $(seq 1 30); do curl -fs localhost:8599/api/health && break; sleep 1; done
          curl -fs localhost:8599/ | grep -q '<div id="root">'
      - uses: actions/upload-artifact@v4
        with: { name: dist, path: server/dist/ }
  pypi:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions: { id-token: write }
    steps:
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - uses: pypa/gh-action-pypi-publish@release/v1
  image:
    needs: build
    runs-on: ubuntu-latest
    permissions: { contents: read, packages: write }
    steps:
      - uses: actions/checkout@v5
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: "${{ github.actor }}", password: "${{ secrets.GITHUB_TOKEN }}" }
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/mittal0802/a2a-workbench
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=raw,value=latest
      - uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
  github-release:
    needs: [pypi, image]
    runs-on: ubuntu-latest
    permissions: { contents: write }
    steps:
      - uses: actions/checkout@v5
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - run: scripts/release-notes.sh "${GITHUB_REF_NAME#v}" > notes.md
      - run: gh release create "$GITHUB_REF_NAME" dist/* --title "$GITHUB_REF_NAME" --notes-file notes.md
        env: { GH_TOKEN: "${{ github.token }}" }
```

Pin third-party actions to full commit SHAs with a version comment before merging. Validate the workflow with `actionlint` (run it via `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest`).

- [ ] **Step 4: Dry run without publishing.** Push a branch and run the `build` job through a temporary `workflow_dispatch` trigger that skips `pypi`, `image` and `github-release` (`if: github.event_name == 'push'`), or run the build steps locally. Expected: wheel builds, smoke install passes. Remove nothing that the tag run needs.

- [ ] **Step 5: Run** `cd server && uv run pytest -q` — Expected: green.

- [ ] **Step 6: Commit**

```bash
git add .github/ scripts/ CHANGELOG.md server/tests/ && git commit -m "ci: tag-driven release to PyPI, GHCR and GitHub releases"
```

---

### Task 6: Docs site (MkDocs Material on GitHub Pages)

**Files:**
- Create: `mkdocs.yml`, `docs/index.md`, `docs/install.md`, `docs/quickstart.md`, `docs/guides/{connect,chat,tasks,faults,security,push,assistant,integrate,health-checks,ci}.md`, `docs/self-hosting.md` (Docker, compose with Postgres, env vars, upgrades, backups), `docs/reference/{cli,checks,configuration}.md`, `docs/mcp.md` (from `docs/agents.md`), `scripts/gen_docs.py`, `.github/workflows/docs.yml`, `docs/requirements.txt` (pinned `mkdocs-material`)
- Test: `server/tests/test_docs.py`

**Interfaces:**
- Consumes: the check registry (`a2a_workbench.core.health.registry.builtin_checks()`), the Typer `app`, `Settings` fields.
- Produces: `scripts/gen_docs.py [--check]` writes (or verifies) `docs/reference/checks.md`, `cli.md`, `configuration.md`.

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_docs.py
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_generated_reference_is_up_to_date():
    out = subprocess.run([sys.executable, str(ROOT / "scripts/gen_docs.py"), "--check"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_every_check_is_documented():
    from a2a_workbench.core.health.registry import builtin_checks
    text = (ROOT / "docs/reference/checks.md").read_text()
    missing = [c.id for c in builtin_checks() if f"`{c.id}`" not in text]
    assert missing == []
```

- [ ] **Step 2: Run** `cd server && uv run pytest tests/test_docs.py -q` — Expected: FAIL (script missing).

- [ ] **Step 3: Implement** `gen_docs.py`: checks table grouped by area (id, title, MUST/SHOULD, spec ref, fix hint); CLI reference from Typer (`typer.main.get_command(app)` walking commands and params — no extra dependency); configuration table from `Settings.model_fields` (env names, defaults, descriptions). `--check` regenerates in memory and exits 1 with a diff if files differ. Write the guide pages from README content and the UI; every page states what a feature does and how to reach it from web, CLI and MCP. `mkdocs.yml`: material theme, light/dark palette, search, `repo_url`, `edit_uri`, `exclude_docs` for `superpowers/`, `design/`, and `upstream-gaps.md` stays published as "Known SDK gaps" (it is useful to users) — record the ruling. `docs.yml`: on push to main, `pip install -r docs/requirements.txt`, `mkdocs build --strict`, deploy with `actions/upload-pages-artifact` + `actions/deploy-pages`. Add `mkdocs build --strict` to CI as a `docs` job so broken links fail PRs.

- [ ] **Step 4: Run** `uv run pytest tests/test_docs.py -q` and `pip install -r docs/requirements.txt && mkdocs build --strict` (in a throwaway venv) — Expected: pass, no warnings.

- [ ] **Step 5: Commit**

```bash
git add mkdocs.yml docs/ scripts/gen_docs.py .github/ server/tests/test_docs.py && git commit -m "docs: MkDocs site with generated check, CLI and configuration reference"
```

GitHub Pages must be enabled (Settings → Pages → GitHub Actions) and needs the repo public on a free plan: that is the maintainer's step.

---

### Task 7: v1.0.0 readiness (stops before the tag)

**Files:**
- Modify: `README.md` (install with `pipx install a2a-workbench` / `uv tool install a2a-workbench` / `docker run ghcr.io/mittal0802/a2a-workbench`, docs link, stability promise, status line "v1.0"), `server/README.md`, `CONTRIBUTING.md` (release steps), spec §12 (record the 7a/7b split)
- Create: `SECURITY.md` (how to report vulnerabilities privately)

- [ ] **Step 1:** Update the files above. README claims must match reality (no feature listed that is not shipped; hosted mode marked "coming").
- [ ] **Step 2:** Full gate: `cd server && uv run ruff check . && uv run ruff format --check . && uv run pytest -q`; Postgres store tests; `cd web && pnpm lint && pnpm test`; `scripts/build.sh && cd web && pnpm e2e`; docker smoke; `mkdocs build --strict`. Expected: all green.
- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "docs: v1.0.0 install, stability promise and security policy"
```

- [ ] **Step 4: STOP and hand over to the maintainer** with this checklist, in order:
  1. Make `mittal0802/a2a-workbench` public.
  2. On pypi.org, add a *pending trusted publisher*: project `a2a-workbench`, owner `mittal0802`, repo `a2a-workbench`, workflow `release.yml`, environment `pypi`. Create the `pypi` environment in the repo settings.
  3. Enable GitHub Pages with source "GitHub Actions".
  4. Approve the tag: `git tag -a v1.0.0 -m "v1.0.0" && git push origin v1.0.0` (no attribution in the tag message).
  5. After the run: set the GHCR package visibility to public; check `pipx install a2a-workbench`, `docker run ghcr.io/mittal0802/a2a-workbench:1.0.0`, and the docs URL.
