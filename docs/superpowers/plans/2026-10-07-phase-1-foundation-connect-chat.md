# Phase 1 — Foundation, Connect, Chat: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A developer can run `uvx a2a-workbench serve` (or `docker run`), connect any A2A agent over JSON-RPC or HTTP+JSON, chat with it using every Part type and every `SendMessageConfiguration` option, reply to `input_required`, stop a task, and see every wire exchange in Inspect. The same operations are available from the CLI with `--json`/NDJSON output.

**Architecture:** One Python package, `a2a_workbench`. `core/` holds settings, the SQLAlchemy store, an in-process event bus, a recording httpx transport, card fetching with signature verification, SDK client building, and the conversation service. `api/` is FastAPI (REST + one WebSocket) and serves the built React SPA. `cli/` is Typer. `fixtures/` is the agent zoo, built with the official `a2a-sdk` server. All A2A traffic goes through `a2a-sdk` `ClientFactory` / `A2ACardResolver`; we only supply the `httpx.AsyncClient`.

**Tech Stack:** Python 3.12+, a2a-sdk 1.2.x (`http-server`, `signing`), FastAPI, SQLAlchemy 2 async + aiosqlite, pydantic-settings, Typer, uvicorn, pytest + pytest-asyncio + respx. Web: React 19, TypeScript, Vite, Tailwind CSS 4, TanStack Query 5, react-router 7, Radix primitives, Vitest + Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-07-a2a-workbench-design.md`

## Global Constraints

- All A2A traffic through `a2a-sdk`; never hand-build A2A JSON, never invent fields (CLAUDE.md rule 1).
- Commits: conventional, personal identity, no AI attribution (CLAUDE.md rule 2; hooks enforce).
- Docstrings describe the function only, never its callers (CLAUDE.md rule 3).
- `a2a_workbench.core` must not import fastapi, typer, starlette or mcp.
- Python `>=3.12`; `a2a-sdk[http-server,signing]>=1.2.2,<1.3`.
- Local server binds `127.0.0.1:8484` by default; state lives in `~/.a2a-workbench/` (override with `A2AW_HOME`); DB URL from `A2AW_DATABASE_URL` or `DATABASE_URL`, default SQLite in the state directory.
- Secrets never logged; `authorization`, `proxy-authorization`, `cookie`, `set-cookie`, `x-api-key` are redacted in recorded exchanges.
- CLI exit codes: 0 ok, 1 checks failed, 2 usage error, 3 connection error, 4 auth error, 5 protocol error, 6 internal error.
- UI copy is plain language first; protocol names appear as secondary text (spec §5.8).

**Spec deviations, recorded in the spec in Task 1:** the agent zoo lives at `server/a2a_workbench/fixtures/` (not top-level `fixtures/`) so `a2a-workbench fixtures` ships in the wheel. Alembic migrations arrive in Phase 7, before the first public release; until then the schema is created with `metadata.create_all`. Exit code 6 is added for internal errors.

## Review Focus

1. **Card URL given as the full card path** (`https://host/.well-known/agent-card.json`, or a custom `.json` path): connecting must work, not double the path. *Test:* Task 5 `test_split_card_url_*`.
2. **Agent unreachable / card is not JSON / card is HTTP 404:** Connect shows a classified, human-readable error, and nothing is saved. *Test:* Task 5 `test_fetch_card_unreachable_raises_card_error`, Task 9 `test_add_agent_unreachable_returns_422`.
3. **gzip-compressed responses:** Inspect shows the decoded JSON, not binary noise. *Test:* Task 4 `test_recording_transport_decodes_gzip_body`.
4. **Browser reconnects mid-stream:** no timeline events lost or duplicated after a WS reconnect. *Test:* Task 10 `test_ws_replays_after_seq_without_duplicates`.
5. **Second message while a task is waiting for input** continues the same task; after a terminal state, a new message starts a new task in the same context. *Test:* Task 8 `test_reply_to_input_required_continues_task` and `test_message_after_completion_starts_new_task_same_context`.

---

## File Structure

```
server/
  pyproject.toml                         # package metadata, deps, scripts, tool config
  a2a_workbench/
    __init__.py                          # __version__
    core/
      __init__.py
      config.py                          # Settings
      bus.py                             # EventBus
      a2a_json.py                        # proto<->JSON helpers, task state names
      store/__init__.py
      store/models.py                    # SQLAlchemy models
      store/db.py                        # Database (engine, sessions, schema)
      exchanges.py                       # ExchangeStore (sink + queries)
      blobs.py                           # BlobService
      connection/__init__.py
      connection/recorder.py             # Exchange, RecordingTransport, recording_scope
      connection/http.py                 # build_http_client
      connection/cards.py                # split_card_url, fetch_card, verify_card_signatures
      connection/client.py               # interface selection, open_client
      registry/__init__.py
      registry/service.py                # AgentService + schemas
      conversations/__init__.py
      conversations/artifacts.py         # ArtifactAssembler
      conversations/timeline.py          # TimelineEvent, event_from_stream_response
      conversations/parts.py             # PartInput models, build_part
      conversations/options.py           # SendOptions, build_request, build_call_context
      conversations/errors.py            # classify_error
      conversations/service.py           # ConversationService
      workbench.py                       # Workbench container
    api/
      __init__.py
      app.py                             # create_app, SPA static serving
      deps.py                            # get_workbench
      errors.py                          # exception handlers
      routes_agents.py
      routes_conversations.py
      routes_misc.py                     # health, blobs, exchanges
      ws.py                              # /ws hub
    cli/
      __init__.py
      main.py                            # Typer app
      output.py                          # human/JSON printers, exit codes
    fixtures/
      __init__.py
      zoo.py                             # ZooExecutor + build_zoo_app
      runner.py                          # ZooServer (thread + free port)
    static/                              # built SPA (gitignored)
  tests/
    conftest.py
    core/...                             # one test module per core module
    api/...
    cli/...
web/
  package.json, vite.config.ts, tsconfig.json, index.html
  src/
    main.tsx, App.tsx, styles.css
    lib/types.ts, lib/api.ts, lib/ws.ts, lib/labels.ts, lib/timeline.ts, lib/parts.ts
    components/{Sidebar,ThemeToggle,Avatar,StatusPill,Switch,Popover,ConnectDialog,JsonView}.tsx
    features/agent/{AgentPage,ConnectionMenu}.tsx
    features/chat/{ChatView,Turn,TaskProgress,PartView,ArtifactCard,AskCard,EventLog,Composer,OptionsMenu}.tsx
    features/inspect/InspectDrawer.tsx
    features/about/AboutView.tsx
    test/setup.ts
  e2e/connect-and-chat.spec.ts, playwright.config.ts
scripts/build.sh, scripts/dev.sh
Dockerfile, .dockerignore, .github/workflows/ci.yml
README.md, CONTRIBUTING.md, NOTICE, docs/upstream-gaps.md
```

---

### Task 1: Python package scaffold, settings, tooling

**Files:**
- Create: `server/pyproject.toml`, `server/a2a_workbench/__init__.py`, `server/a2a_workbench/core/__init__.py`, `server/a2a_workbench/core/config.py`, `server/tests/conftest.py`, `server/tests/core/test_config.py`
- Modify: `.gitignore`, `docs/superpowers/specs/2026-10-07-a2a-workbench-design.md` (deviations listed above)

**Interfaces:**
- Produces: `Settings` (fields `home: Path`, `database_url: str | None`, `host: str`, `port: int`, `mode: Literal["local","hosted"]`, `max_blob_bytes: int`, `max_recorded_body_bytes: int`; property `resolved_database_url: str`); `__version__: str`.

- [ ] **Step 1: Write `server/pyproject.toml`**

```toml
[project]
name = "a2a-workbench"
version = "0.1.0"
description = "Debug, test and conformance-check any A2A agent: web UI, CLI and MCP server built on the official a2a-sdk"
readme = "../README.md"
license = "Apache-2.0"
requires-python = ">=3.12"
authors = [{ name = "Keshav Mittal", email = "mittalkeshav41@gmail.com" }]
dependencies = [
  "a2a-sdk[http-server,signing]>=1.2.2,<1.3",
  "cryptography>=43",
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlalchemy[asyncio]>=2.0",
  "aiosqlite>=0.20",
  "pydantic>=2.11",
  "pydantic-settings>=2.6",
  "python-multipart>=0.0.20",
  "typer>=0.15",
  "httpx>=0.28.1",
]

[project.scripts]
a2a-workbench = "a2a_workbench.cli.main:app"

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.25", "respx>=0.22", "ruff>=0.9", "mypy>=1.14"]

[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["a2a_workbench"]
artifacts = ["a2a_workbench/static/**"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "ASYNC", "RUF"]

[tool.mypy]
python_version = "3.12"
ignore_missing_imports = true
```

- [ ] **Step 2: Write the failing test** `server/tests/core/test_config.py`

```python
from pathlib import Path

from a2a_workbench.core.config import Settings


def test_defaults_use_home_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("A2AW_HOME", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings()
    assert s.home == tmp_path
    assert s.host == "127.0.0.1"
    assert s.port == 8484
    assert s.mode == "local"
    assert s.resolved_database_url == f"sqlite+aiosqlite:///{tmp_path / 'workbench.db'}"


def test_database_url_accepts_unprefixed_env(tmp_path, monkeypatch):
    monkeypatch.setenv("A2AW_HOME", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    assert Settings().resolved_database_url == "postgresql+asyncpg://u:p@h/db"


def test_default_home_is_dot_dir(monkeypatch):
    monkeypatch.delenv("A2AW_HOME", raising=False)
    assert Settings().home == Path.home() / ".a2a-workbench"
```

- [ ] **Step 3: Run it, expect failure**

Run: `cd server && uv sync && uv run pytest tests/core/test_config.py -q`
Expected: FAIL, `ModuleNotFoundError: a2a_workbench`

- [ ] **Step 4: Implement**

`server/a2a_workbench/__init__.py`:
```python
"""A2A Workbench: debug, test and conformance-check A2A agents."""

__version__ = "0.1.0"
```

`server/a2a_workbench/core/__init__.py`: `"""UI-independent core of A2A Workbench."""`

`server/a2a_workbench/core/config.py`:
```python
"""Runtime configuration."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration read from ``A2AW_*`` environment variables.

    ``database_url`` also accepts the conventional unprefixed ``DATABASE_URL``.
    """

    model_config = SettingsConfigDict(env_prefix="A2AW_", extra="ignore")

    home: Path = Field(default_factory=lambda: Path.home() / ".a2a-workbench")
    database_url: str | None = Field(
        default=None, validation_alias=AliasChoices("A2AW_DATABASE_URL", "DATABASE_URL")
    )
    host: str = "127.0.0.1"
    port: int = 8484
    mode: Literal["local", "hosted"] = "local"
    max_blob_bytes: int = 20 * 1024 * 1024
    max_recorded_body_bytes: int = 1024 * 1024

    @property
    def resolved_database_url(self) -> str:
        """Return the configured database URL, or a SQLite file inside ``home``."""
        return self.database_url or f"sqlite+aiosqlite:///{self.home / 'workbench.db'}"
```

`server/tests/conftest.py`:
```python
import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("A2AW_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("A2AW_DATABASE_URL", raising=False)
```

Append to `.gitignore`: `server/.venv/`, `__pycache__/`, `*.pyc`, `server/a2a_workbench/static/`, `web/node_modules/`, `web/dist/`, `web/test-results/`, `web/playwright-report/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `*.db`.

Edit the spec: §4.1 note that fixtures live in `server/a2a_workbench/fixtures/`; §5.9 exit codes add `6 internal error`; §12 Phase 1 note "schema via create_all; Alembic in Phase 7".

- [ ] **Step 5: Run tests, expect pass**, then `uv run ruff check . && uv run ruff format --check .`
- [ ] **Step 6: Commit** `chore: scaffold python package and settings`

---

### Task 2: Store models, database, event bus, JSON helpers

**Files:**
- Create: `core/store/__init__.py`, `core/store/models.py`, `core/store/db.py`, `core/bus.py`, `core/a2a_json.py`
- Test: `tests/core/test_db.py`, `tests/core/test_bus.py`, `tests/core/test_a2a_json.py`

**Interfaces:**
- Produces:
  - `Database(url: str)` with `.sessions: async_sessionmaker[AsyncSession]`, `async create_schema()`, `async dispose()`.
  - Models `Workspace`, `Agent`, `Conversation`, `TimelineEventRow`, `ExchangeRow`, `Blob`; constant `DEFAULT_WORKSPACE_ID = "default"`.
  - `EventBus` with `publish(topic: str, payload: dict) -> None` and `subscription(topic) -> AsyncContextManager[asyncio.Queue[dict]]`.
  - `to_json(msg) -> dict`, `card_from_json(d) -> AgentCard`, `state_name(state: int) -> str`, `TERMINAL_STATES: frozenset[str]`, `INTERRUPTED_STATES: frozenset[str]`.

- [ ] **Step 1: Failing tests**

`tests/core/test_a2a_json.py`:
```python
from a2a.types import AgentCard, Part, TaskState

from a2a_workbench.core.a2a_json import (
    INTERRUPTED_STATES, TERMINAL_STATES, card_from_json, state_name, to_json,
)


def test_state_names_cover_every_task_state():
    names = {state_name(v) for v in TaskState.values()}
    assert names == {
        "unspecified", "submitted", "working", "completed", "failed",
        "canceled", "input_required", "rejected", "auth_required",
    }


def test_terminal_and_interrupted_sets():
    assert TERMINAL_STATES == {"completed", "failed", "canceled", "rejected"}
    assert INTERRUPTED_STATES == {"input_required", "auth_required"}


def test_to_json_uses_camel_case():
    assert to_json(Part(text="hi", media_type="text/plain")) == {"text": "hi", "mediaType": "text/plain"}


def test_card_round_trip():
    card = AgentCard(name="a", description="d", version="1")
    assert card_from_json(to_json(card)) == card
```

`tests/core/test_bus.py`:
```python
import asyncio

from a2a_workbench.core.bus import EventBus


async def test_publish_reaches_only_matching_subscribers():
    bus = EventBus()
    async with bus.subscription("a") as qa, bus.subscription("b") as qb:
        bus.publish("a", {"n": 1})
        assert await asyncio.wait_for(qa.get(), 1) == {"n": 1}
        assert qb.empty()


async def test_unsubscribed_queue_receives_nothing():
    bus = EventBus()
    async with bus.subscription("a") as q:
        pass
    bus.publish("a", {"n": 1})
    assert q.empty()
```

`tests/core/test_db.py`:
```python
from sqlalchemy import select

from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import DEFAULT_WORKSPACE_ID, Agent, Workspace


async def test_create_schema_and_insert(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    await db.create_schema()
    async with db.sessions() as s:
        s.add(Workspace(id=DEFAULT_WORKSPACE_ID, name="Default"))
        s.add(Agent(workspace_id=DEFAULT_WORKSPACE_ID, name="x", base_url="http://x",
                    card={"name": "x"}, signature_status="unsigned"))
        await s.commit()
        agent = (await s.execute(select(Agent))).scalar_one()
    assert len(agent.id) == 32
    assert agent.created_at is not None
    await db.dispose()
```

- [ ] **Step 2: Run, expect import failures.** `uv run pytest tests/core -q`

- [ ] **Step 3: Implement**

`core/a2a_json.py`:
```python
"""Conversion between A2A protobuf messages and their canonical JSON form."""

from typing import Any

from a2a.types import AgentCard, TaskState
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.message import Message as ProtoMessage

_STATE_PREFIX = "TASK_STATE_"

TERMINAL_STATES = frozenset({"completed", "failed", "canceled", "rejected"})
INTERRUPTED_STATES = frozenset({"input_required", "auth_required"})


def to_json(message: ProtoMessage) -> dict[str, Any]:
    """Return the canonical A2A JSON (camelCase keys) of a protobuf message."""
    return MessageToDict(message)


def card_from_json(data: dict[str, Any]) -> AgentCard:
    """Parse an ``AgentCard`` from its canonical JSON form, ignoring unknown keys."""
    return ParseDict(data, AgentCard(), ignore_unknown_fields=True)


def state_name(state: int) -> str:
    """Return the lowercase short name of a ``TaskState`` value, e.g. ``input_required``."""
    return TaskState.Name(state).removeprefix(_STATE_PREFIX).lower()
```

`core/bus.py`:
```python
"""In-process publish/subscribe."""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


class EventBus:
    """Delivers JSON-serializable payloads to every current subscriber of a topic.

    Delivery is fire-and-forget: publishing never blocks, and a payload published
    while nobody is subscribed is dropped.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Enqueue ``payload`` on every queue subscribed to ``topic``."""
        for queue in tuple(self._subscribers.get(topic, ())):
            queue.put_nowait(payload)

    @asynccontextmanager
    async def subscription(self, topic: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """Yield a queue that receives payloads published to ``topic`` until exit."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[topic].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[topic].discard(queue)
            if not self._subscribers[topic]:
                del self._subscribers[topic]
```

`core/store/models.py`:
```python
"""Relational schema of the Workbench state."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_WORKSPACE_ID = "default"


def new_id() -> str:
    """Return a random 32-character hexadecimal identifier."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base with JSON mapped for ``dict``/``list`` annotations."""

    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Workspace(Base):
    __tablename__ = "workspace"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class Agent(Base):
    __tablename__ = "agent"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(2000))
    card_path: Mapped[str | None] = mapped_column(String(500), default=None)
    card: Mapped[dict[str, Any]]
    signature_status: Mapped[str] = mapped_column(String(20))
    signature_detail: Mapped[str | None] = mapped_column(String(1000), default=None)
    selected_interface_url: Mapped[str | None] = mapped_column(String(2000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Conversation(Base):
    __tablename__ = "conversation"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    origin: Mapped[str] = mapped_column(String(20), default="chat")
    context_id: Mapped[str | None] = mapped_column(String(200), default=None)
    task_id: Mapped[str | None] = mapped_column(String(200), default=None)
    task_state: Mapped[str | None] = mapped_column(String(30), default=None)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TimelineEventRow(Base):
    __tablename__ = "timeline_event"
    __table_args__ = (UniqueConstraint("conversation_id", "seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversation.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    task_id: Mapped[str | None] = mapped_column(String(200), default=None)
    context_id: Mapped[str | None] = mapped_column(String(200), default=None)
    exchange_id: Mapped[str | None] = mapped_column(String(32), default=None)
    data: Mapped[dict[str, Any]]


class ExchangeRow(Base):
    __tablename__ = "exchange"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True, default=DEFAULT_WORKSPACE_ID)
    agent_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    conversation_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    operation: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(default=None)
    status: Mapped[int | None] = mapped_column(Integer, default=None)
    error: Mapped[str | None] = mapped_column(String(2000), default=None)
    record: Mapped[dict[str, Any]]


class Blob(Base):
    __tablename__ = "blob"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True, default=DEFAULT_WORKSPACE_ID)
    media_type: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str | None] = mapped_column(String(500), default=None)
    size: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

`core/store/db.py`:
```python
"""Async database engine and sessions."""

from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from a2a_workbench.core.store.models import Base


class Database:
    """Owns one async SQLAlchemy engine and a session factory bound to it."""

    def __init__(self, url: str) -> None:
        parsed = make_url(url)
        if parsed.get_backend_name() == "sqlite" and parsed.database:
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_async_engine(url)
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def create_schema(self) -> None:
        """Create every table that does not exist yet."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        """Close all pooled connections."""
        await self.engine.dispose()
```

`core/store/__init__.py`: `"""Persistence layer."""`

- [ ] **Step 4: Run** `uv run pytest tests/core -q` → PASS
- [ ] **Step 5: Commit** `feat(core): store models, database, event bus and A2A JSON helpers`

---

### Task 3: Agent zoo — `compliant` fixture agent and runner

The zoo comes before the client code, so every client test runs against a real SDK server.

**Files:**
- Create: `fixtures/__init__.py`, `fixtures/zoo.py`, `fixtures/runner.py`
- Test: `tests/fixtures/test_zoo.py`

**Interfaces:**
- Produces:
  - `build_zoo_app(base_url: str, *, signed: bool = True) -> Starlette`: serves card at `/.well-known/agent-card.json`, JWKS at `/.well-known/jwks.json`, JSON-RPC at `/a2a`, HTTP+JSON at `/v1`.
  - `ZooServer(signed: bool = True)`: context manager (sync and async) exposing `.base_url`.
  - Executor behaviours, selected by the first word of the user text: `echo` (default), `stream`, `ask`, `message`, `data`, `file`, `fail`, `reject`, `slow <seconds>`, `auth`, `inspect`.

- [ ] **Step 1: Failing test** `tests/fixtures/test_zoo.py`

```python
import httpx

from a2a_workbench.fixtures.runner import ZooServer


def test_zoo_serves_signed_card_and_jwks():
    with ZooServer() as zoo:
        card = httpx.get(f"{zoo.base_url}/.well-known/agent-card.json").json()
        jwks = httpx.get(f"{zoo.base_url}/.well-known/jwks.json").json()
    assert card["name"] == "Zoo agent"
    bindings = {i["protocolBinding"] for i in card["supportedInterfaces"]}
    assert bindings == {"JSONRPC", "HTTP+JSON"}
    assert card["capabilities"]["streaming"] is True
    assert card["signatures"]
    assert jwks["keys"][0]["kid"] == "zoo-1"


def test_unsigned_zoo_has_no_signatures():
    with ZooServer(signed=False) as zoo:
        card = httpx.get(f"{zoo.base_url}/.well-known/agent-card.json").json()
    assert "signatures" not in card
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** `fixtures/zoo.py`

```python
"""Agent zoo: A2A agents built with the official SDK server, for tests and demos."""

import asyncio
import base64
import json
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities, AgentCard, AgentInterface, AgentProvider, AgentSkill, Part, Task,
    TaskState, TaskStatus,
)
from a2a.utils.signing import create_agent_card_signer
from cryptography.hazmat.primitives.asymmetric import ec
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Value
from jwt.algorithms import ECAlgorithm
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

KEY_ID = "zoo-1"
# 1x1 transparent PNG.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _data_value(obj: Any) -> Value:
    value = Value()
    value.MergeFrom(Value())
    from google.protobuf.json_format import ParseDict

    return ParseDict(obj, value)


class ZooExecutor(AgentExecutor):
    """Agent whose behaviour is chosen by the first word of the user's text.

    ``echo`` (default) replies with an artifact repeating the text; ``stream``
    sends a four-chunk artifact; ``ask`` enters ``input_required`` and completes
    on the reply; ``message`` answers with a direct Message; ``data`` and
    ``file`` return structured and file parts; ``fail`` and ``reject`` end in
    those states; ``slow <seconds>`` works for that long; ``auth`` enters
    ``auth_required``; ``inspect`` returns a data artifact describing the
    received message, configuration and requested extensions.
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Run the behaviour selected by the user text and publish its events."""
        text = context.get_user_input().strip()
        word, _, rest = text.partition(" ")
        word = word.lower()
        task = context.current_task
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        if word == "message" and task is None:
            await event_queue.enqueue_event(
                updater.new_agent_message([Part(text=f"Direct reply: {rest or 'hello'}")])
            )
            return

        if task is None:
            await event_queue.enqueue_event(
                Task(
                    id=context.task_id, context_id=context.context_id,
                    status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                    history=[context.message],
                )
            )
        elif task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
            await updater.start_work()
            await updater.add_artifact([Part(text=f"You chose: {text}")], name="answer")
            await updater.complete()
            return

        await updater.start_work(updater.new_agent_message([Part(text="Working on it…")]))
        await self._behave(word, rest, text, context, updater)

    async def _behave(
        self, word: str, rest: str, text: str, context: RequestContext, updater: TaskUpdater
    ) -> None:
        if word == "stream":
            for i, chunk in enumerate(["Streaming ", "in ", "four ", "pieces."]):
                await asyncio.sleep(0.05)
                await updater.add_artifact(
                    [Part(text=chunk)], artifact_id="stream-1", name="streamed",
                    append=i > 0, last_chunk=i == 3,
                )
            await updater.complete()
        elif word == "ask":
            await updater.requires_input(
                updater.new_agent_message([Part(text="Which option should I pick: A or B?")])
            )
        elif word == "data":
            await updater.add_artifact(
                [Part(data=_data_value({"ok": True, "items": [1, 2, 3]}), media_type="application/json")],
                name="data",
            )
            await updater.complete()
        elif word == "file":
            await updater.add_artifact(
                [
                    Part(raw=PNG_1PX, media_type="image/png", filename="pixel.png"),
                    Part(url="https://a2a-protocol.org/", media_type="text/html", filename="a2a.html"),
                ],
                name="files",
            )
            await updater.complete()
        elif word == "fail":
            await updater.failed(updater.new_agent_message([Part(text="Something went wrong.")]))
        elif word == "reject":
            await updater.reject(updater.new_agent_message([Part(text="I won't do that.")]))
        elif word == "slow":
            await asyncio.sleep(float(rest or "5"))
            await updater.complete(updater.new_agent_message([Part(text="Finally done.")]))
        elif word == "auth":
            await updater.requires_auth(updater.new_agent_message([Part(text="Please sign in.")]))
        elif word == "inspect":
            report = {
                "message": MessageToDict(context.message) if context.message else None,
                "configuration": MessageToDict(context.configuration) if context.configuration else None,
                "requestedExtensions": sorted(context.requested_extensions),
            }
            await updater.add_artifact(
                [Part(data=_data_value(json.loads(json.dumps(report))))], name="inspect"
            )
            await updater.complete()
        else:
            await updater.add_artifact([Part(text=text or "(empty)")], name="echo")
            await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Mark the task canceled."""
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def build_zoo_card(base_url: str) -> AgentCard:
    """Return the public card of the zoo agent served at ``base_url``."""
    return AgentCard(
        name="Zoo agent",
        description="Reference A2A agent for testing A2A Workbench.",
        version="1.0.0",
        provider=AgentProvider(organization="A2A Workbench", url="https://github.com/mittal0802/a2a-workbench"),
        documentation_url="https://github.com/mittal0802/a2a-workbench",
        supported_interfaces=[
            AgentInterface(url=f"{base_url}/a2a", protocol_binding="JSONRPC", protocol_version="1.0"),
            AgentInterface(url=f"{base_url}/v1", protocol_binding="HTTP+JSON", protocol_version="1.0"),
        ],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain", "application/json", "image/png"],
        default_output_modes=["text/plain", "application/json", "image/png"],
        skills=[
            AgentSkill(id="echo", name="Echo", description="Repeats what you send.",
                       tags=["test"], examples=["echo hello"]),
            AgentSkill(id="stream", name="Stream", description="Streams a four-piece artifact.",
                       tags=["test", "streaming"], examples=["stream"]),
            AgentSkill(id="ask", name="Ask", description="Asks a question before finishing.",
                       tags=["test"], examples=["ask"]),
        ],
    )


def build_zoo_app(base_url: str, *, signed: bool = True) -> Starlette:
    """Return an ASGI app serving the zoo agent, its card and its JWKS."""
    card = build_zoo_card(base_url)
    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(ECAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": KEY_ID, "alg": "ES256", "use": "sig"})
    if signed:
        signer = create_agent_card_signer(
            private_key,
            {"kid": KEY_ID, "alg": "ES256", "jku": f"{base_url}/.well-known/jwks.json", "typ": "JOSE"},
        )
        card = signer(card)

    handler = DefaultRequestHandlerV2(
        agent_executor=ZooExecutor(), task_store=InMemoryTaskStore(), agent_card=card
    )

    async def jwks(_: Request) -> JSONResponse:
        return JSONResponse({"keys": [jwk]})

    routes = [
        *create_agent_card_routes(card),
        Route("/.well-known/jwks.json", jwks),
        *create_jsonrpc_routes(handler, "/a2a"),
        *create_rest_routes(handler, path_prefix="/v1"),
    ]
    return Starlette(routes=routes)
```

`fixtures/runner.py`:
```python
"""Run zoo agents on a free local port in a background thread."""

import socket
import threading
import time
from types import TracebackType

import httpx
import uvicorn

from a2a_workbench.fixtures.zoo import build_zoo_app


def free_port(host: str = "127.0.0.1") -> int:
    """Return a TCP port that is currently free on ``host``."""
    with socket.socket() as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


class ZooServer:
    """Serves the zoo agent with uvicorn in a daemon thread while the context is open."""

    def __init__(self, *, signed: bool = True, host: str = "127.0.0.1", port: int | None = None):
        self.host = host
        self.port = port or free_port(host)
        self.base_url = f"http://{host}:{self.port}"
        app = build_zoo_app(self.base_url, signed=signed)
        self._server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=self.port, log_level="warning", lifespan="off")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self, timeout: float = 10.0) -> None:
        """Start serving and block until the card endpoint answers."""
        self._thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                httpx.get(f"{self.base_url}/.well-known/agent-card.json", timeout=0.5)
                return
            except httpx.TransportError:
                time.sleep(0.05)
        raise RuntimeError(f"zoo agent did not start on {self.base_url}")

    def stop(self) -> None:
        """Ask the server to exit and wait for its thread."""
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def __enter__(self) -> "ZooServer":
        self.start()
        return self

    def __exit__(self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None) -> None:
        self.stop()

    async def __aenter__(self) -> "ZooServer":
        import asyncio
        await asyncio.to_thread(self.start)
        return self

    async def __aexit__(self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None) -> None:
        import asyncio
        await asyncio.to_thread(self.stop)
```

Add to `tests/conftest.py`:
```python
@pytest.fixture(scope="session")
def zoo():
    from a2a_workbench.fixtures.runner import ZooServer
    with ZooServer() as server:
        yield server


@pytest.fixture(scope="session")
def unsigned_zoo():
    from a2a_workbench.fixtures.runner import ZooServer
    with ZooServer(signed=False) as server:
        yield server
```

- [ ] **Step 4: Run** `uv run pytest tests/fixtures -q` → PASS (fix `_data_value` to a plain `ParseDict(obj, Value())` once confirmed)
- [ ] **Step 5: Commit** `test: add zoo reference agent built on the a2a-sdk server`

---

### Task 4: Recording transport and exchange store

**Files:**
- Create: `core/connection/__init__.py`, `core/connection/recorder.py`, `core/connection/http.py`, `core/exchanges.py`
- Test: `tests/core/test_recorder.py`, `tests/core/test_exchanges.py`

**Interfaces:**
- Produces:
  - `Exchange` dataclass: `id, operation, http_method, url, started_at, request_headers, request_body, status, response_headers, response_body, frames: list[Frame], duration_ms, error, truncated, agent_id, conversation_id`; `to_record() -> dict`.
  - `Frame(t_ms: float, data: str)`.
  - `ExchangeSink = Callable[[Exchange], Awaitable[None]]`.
  - `recording_scope(operation: str, *, agent_id=None, conversation_id=None) -> ContextManager[RecordingScope]`; `RecordingScope.exchange_ids: list[str]`.
  - `RecordingTransport(sink, inner=None, *, max_body_bytes=1_048_576)`.
  - `build_http_client(sink, *, max_body_bytes=1_048_576) -> httpx.AsyncClient`.
  - `ExchangeStore(db, bus)`: is an `ExchangeSink`; `async list(*, conversation_id=None, agent_id=None, limit=200) -> list[dict]`; `async get(exchange_id) -> dict | None`. Publishes `{"type": "exchange", "exchange": summary}` to `exchanges:<conversation_id>`.

- [ ] **Step 1: Failing tests** `tests/core/test_recorder.py`

```python
import gzip
import json

import httpx
import pytest

from a2a_workbench.core.connection.recorder import (
    Exchange, RecordingTransport, recording_scope,
)


class Collector:
    def __init__(self):
        self.items: list[Exchange] = []

    async def __call__(self, ex: Exchange) -> None:
        self.items.append(ex)


def _client(handler, sink, **kw):
    return httpx.AsyncClient(transport=RecordingTransport(sink, httpx.MockTransport(handler), **kw))


async def test_records_json_request_and_response_with_redaction():
    sink = Collector()
    def handler(req):
        return httpx.Response(200, json={"ok": True})
    async with _client(handler, sink) as c:
        with recording_scope("send_message", agent_id="a1", conversation_id="c1") as scope:
            await c.post("http://x/a2a", json={"m": 1}, headers={"Authorization": "Bearer s3cret"})
    ex = sink.items[0]
    assert scope.exchange_ids == [ex.id]
    assert (ex.operation, ex.agent_id, ex.conversation_id) == ("send_message", "a1", "c1")
    assert ex.request_headers["authorization"] == "••••"
    assert json.loads(ex.request_body) == {"m": 1}
    assert ex.status == 200 and json.loads(ex.response_body) == {"ok": True}
    assert ex.duration_ms is not None and ex.error is None


async def test_records_sse_frames_in_order():
    sink = Collector()
    body = b"data: {\"a\":1}\n\ndata: {\"a\":2}\n\n"
    def handler(req):
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
    async with _client(handler, sink) as c:
        async with c.stream("POST", "http://x/a2a", json={}) as r:
            async for _ in r.aiter_bytes():
                pass
    assert [f.data for f in sink.items[0].frames] == ['data: {"a":1}', 'data: {"a":2}']
    assert sink.items[0].response_body is None


async def test_recording_transport_decodes_gzip_body():
    sink = Collector()
    def handler(req):
        return httpx.Response(200, content=gzip.compress(b'{"z":1}'),
                              headers={"content-encoding": "gzip", "content-type": "application/json"})
    async with _client(handler, sink) as c:
        r = await c.get("http://x/card")
    assert r.json() == {"z": 1}
    assert sink.items[0].response_body == '{"z":1}'


async def test_truncates_large_bodies():
    sink = Collector()
    def handler(req):
        return httpx.Response(200, content=b"x" * 100)
    async with _client(handler, sink, max_body_bytes=10) as c:
        await c.get("http://x/")
    assert sink.items[0].truncated is True
    assert len(sink.items[0].response_body) == 10


async def test_transport_error_is_recorded_and_reraised():
    sink = Collector()
    def handler(req):
        raise httpx.ConnectError("refused")
    async with _client(handler, sink) as c:
        with pytest.raises(httpx.ConnectError):
            await c.get("http://x/")
    assert sink.items[0].error.startswith("ConnectError")
    assert sink.items[0].status is None


async def test_without_scope_operation_is_http():
    sink = Collector()
    async with _client(lambda r: httpx.Response(204), sink) as c:
        await c.get("http://x/")
    assert sink.items[0].operation == "http"
```

`tests/core/test_exchanges.py`:
```python
from datetime import UTC, datetime

from a2a_workbench.core.bus import EventBus
from a2a_workbench.core.connection.recorder import Exchange
from a2a_workbench.core.exchanges import ExchangeStore
from a2a_workbench.core.store.db import Database


async def test_store_persists_and_publishes(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'x.db'}")
    await db.create_schema()
    bus = EventBus()
    store = ExchangeStore(db, bus)
    ex = Exchange(id="e1", operation="send_message", http_method="POST", url="http://x/a2a",
                  started_at=datetime.now(UTC), conversation_id="c1", status=200)
    async with bus.subscription("exchanges:c1") as q:
        await store(ex)
        msg = q.get_nowait()
    assert msg["type"] == "exchange" and msg["exchange"]["id"] == "e1"
    assert (await store.get("e1"))["url"] == "http://x/a2a"
    assert [e["id"] for e in await store.list(conversation_id="c1")] == ["e1"]
    await db.dispose()
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** `core/connection/recorder.py`

```python
"""Recording of every HTTP exchange made on behalf of the A2A SDK."""

import time
import uuid
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

REDACTED = "••••"
SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
)
DEFAULT_MAX_BODY_BYTES = 1024 * 1024


@dataclass
class Frame:
    """One server-sent event, with its arrival time relative to the request start."""

    t_ms: float
    data: str


@dataclass
class Exchange:
    """A single HTTP request/response pair, with streamed frames for SSE responses."""

    id: str
    operation: str
    http_method: str
    url: str
    started_at: datetime
    request_headers: dict[str, str] = field(default_factory=dict)
    request_body: str | None = None
    status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: str | None = None
    frames: list[Frame] = field(default_factory=list)
    duration_ms: float | None = None
    error: str | None = None
    truncated: bool = False
    agent_id: str | None = None
    conversation_id: str | None = None

    def to_record(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of every field."""
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        return data


ExchangeSink = Callable[[Exchange], Awaitable[None]]


@dataclass
class RecordingScope:
    """Labels attached to exchanges recorded while the scope is active."""

    operation: str
    agent_id: str | None = None
    conversation_id: str | None = None
    exchange_ids: list[str] = field(default_factory=list)


_current_scope: ContextVar[RecordingScope | None] = ContextVar("a2aw_recording_scope", default=None)


@contextmanager
def recording_scope(
    operation: str, *, agent_id: str | None = None, conversation_id: str | None = None
) -> Iterator[RecordingScope]:
    """Label exchanges recorded in this context and collect their ids."""
    scope = RecordingScope(operation, agent_id, conversation_id)
    token = _current_scope.set(scope)
    try:
        yield scope
    finally:
        _current_scope.reset(token)


def redact_headers(headers: httpx.Headers) -> dict[str, str]:
    """Return headers as a lowercase dict with credential-bearing values masked."""
    return {
        k.lower(): (REDACTED if k.lower() in SENSITIVE_HEADERS else v)
        for k, v in headers.multi_items()
    }


def _decoder(content_encoding: str) -> "zlib._Decompress | None":
    encoding = content_encoding.strip().lower()
    if encoding == "gzip":
        return zlib.decompressobj(zlib.MAX_WBITS | 16)
    if encoding == "deflate":
        return zlib.decompressobj()
    return None


class _RecordingStream(httpx.AsyncByteStream):
    """Passes response bytes through unchanged while copying them into an Exchange."""

    def __init__(
        self, inner: httpx.AsyncByteStream, exchange: Exchange, started: float,
        sink: ExchangeSink, *, is_sse: bool, max_body_bytes: int, content_encoding: str,
    ) -> None:
        self._inner = inner
        self._ex = exchange
        self._started = started
        self._sink = sink
        self._is_sse = is_sse
        self._max = max_body_bytes
        self._decoder = _decoder(content_encoding)
        self._undecodable = bool(content_encoding) and self._decoder is None
        self._body = bytearray()
        self._sse_buffer = ""
        self._done = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._inner:
                self._capture(chunk)
                yield chunk
        except Exception as exc:
            self._ex.error = f"{type(exc).__name__}: {exc}"
            raise

    def _capture(self, chunk: bytes) -> None:
        if self._undecodable:
            return
        data = self._decoder.decompress(chunk) if self._decoder else chunk
        if self._is_sse:
            self._sse_buffer += data.decode("utf-8", errors="replace").replace("\r\n", "\n")
            while "\n\n" in self._sse_buffer:
                frame, self._sse_buffer = self._sse_buffer.split("\n\n", 1)
                if frame.strip():
                    self._ex.frames.append(Frame(self._elapsed(), frame))
        else:
            room = self._max - len(self._body)
            if len(data) > room:
                self._ex.truncated = True
            self._body.extend(data[: max(room, 0)])

    def _elapsed(self) -> float:
        return round((time.perf_counter() - self._started) * 1000, 2)

    async def aclose(self) -> None:
        try:
            await self._inner.aclose()
        finally:
            await self._finish()

    async def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        if self._is_sse and self._sse_buffer.strip():
            self._ex.frames.append(Frame(self._elapsed(), self._sse_buffer.strip()))
        if self._undecodable:
            self._ex.response_body = "(compressed body not decoded)"
        elif not self._is_sse:
            self._ex.response_body = self._body.decode("utf-8", errors="replace")
        self._ex.duration_ms = self._elapsed()
        await self._sink(self._ex)


class RecordingTransport(httpx.AsyncBaseTransport):
    """httpx transport that records each request and response it carries.

    Bytes reach the caller unmodified. A record is handed to ``sink`` once the
    response body is closed, or immediately when the request fails.
    """

    def __init__(
        self, sink: ExchangeSink, inner: httpx.AsyncBaseTransport | None = None,
        *, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self._sink = sink
        self._inner = inner or httpx.AsyncHTTPTransport()
        self._max = max_body_bytes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Forward ``request`` to the inner transport and record the exchange."""
        scope = _current_scope.get()
        exchange = Exchange(
            id=uuid.uuid4().hex,
            operation=scope.operation if scope else "http",
            http_method=request.method,
            url=str(request.url),
            started_at=datetime.now(UTC),
            request_headers=redact_headers(request.headers),
            request_body=self._request_body(request),
            agent_id=scope.agent_id if scope else None,
            conversation_id=scope.conversation_id if scope else None,
        )
        if scope:
            scope.exchange_ids.append(exchange.id)
        started = time.perf_counter()
        try:
            response = await self._inner.handle_async_request(request)
        except Exception as exc:
            exchange.error = f"{type(exc).__name__}: {exc}"
            exchange.duration_ms = round((time.perf_counter() - started) * 1000, 2)
            await self._sink(exchange)
            raise
        exchange.status = response.status_code
        exchange.response_headers = redact_headers(response.headers)
        content_type = response.headers.get("content-type", "")
        stream = _RecordingStream(
            response.stream, exchange, started, self._sink,
            is_sse=content_type.startswith("text/event-stream"),
            max_body_bytes=self._max,
            content_encoding=response.headers.get("content-encoding", ""),
        )
        return httpx.Response(
            status_code=response.status_code, headers=response.headers, stream=stream,
            extensions=response.extensions, request=request,
        )

    def _request_body(self, request: httpx.Request) -> str | None:
        try:
            content = request.content
        except httpx.RequestNotRead:
            return "(streamed request body not recorded)"
        if not content:
            return None
        return content[: self._max].decode("utf-8", errors="replace")

    async def aclose(self) -> None:
        """Close the inner transport."""
        await self._inner.aclose()
```

`core/connection/http.py`:
```python
"""httpx clients configured for A2A traffic."""

import httpx

from a2a_workbench.core.connection.recorder import (
    DEFAULT_MAX_BODY_BYTES, ExchangeSink, RecordingTransport,
)

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


def build_http_client(
    sink: ExchangeSink, *, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    inner: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Return an httpx client whose every exchange is recorded to ``sink``."""
    return httpx.AsyncClient(
        transport=RecordingTransport(sink, inner, max_body_bytes=max_body_bytes),
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    )
```

`core/exchanges.py`:
```python
"""Persistence and live publication of recorded exchanges."""

from typing import Any

from sqlalchemy import select

from a2a_workbench.core.bus import EventBus
from a2a_workbench.core.connection.recorder import Exchange
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import ExchangeRow


def summarize(record: dict[str, Any]) -> dict[str, Any]:
    """Return the list-view fields of an exchange record."""
    keys = ("id", "operation", "http_method", "url", "started_at", "status",
            "duration_ms", "error", "agent_id", "conversation_id")
    summary = {k: record.get(k) for k in keys}
    summary["frame_count"] = len(record.get("frames") or [])
    return summary


class ExchangeStore:
    """Stores exchanges and announces each one on ``exchanges:<conversation_id>``."""

    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus

    async def __call__(self, exchange: Exchange) -> None:
        """Persist ``exchange`` and publish its summary."""
        record = exchange.to_record()
        async with self._db.sessions() as session:
            session.add(ExchangeRow(
                id=exchange.id, agent_id=exchange.agent_id,
                conversation_id=exchange.conversation_id, operation=exchange.operation,
                started_at=exchange.started_at, duration_ms=exchange.duration_ms,
                status=exchange.status, error=exchange.error, record=record,
            ))
            await session.commit()
        if exchange.conversation_id:
            self._bus.publish(f"exchanges:{exchange.conversation_id}",
                              {"type": "exchange", "exchange": summarize(record)})

    async def get(self, exchange_id: str) -> dict[str, Any] | None:
        """Return the full record of one exchange, or None."""
        async with self._db.sessions() as session:
            row = await session.get(ExchangeRow, exchange_id)
            return row.record if row else None

    async def list(
        self, *, conversation_id: str | None = None, agent_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Return exchange summaries, oldest first, optionally filtered."""
        query = select(ExchangeRow).order_by(ExchangeRow.started_at.desc()).limit(limit)
        if conversation_id:
            query = query.where(ExchangeRow.conversation_id == conversation_id)
        if agent_id:
            query = query.where(ExchangeRow.agent_id == agent_id)
        async with self._db.sessions() as session:
            rows = (await session.execute(query)).scalars().all()
        return [summarize(r.record) for r in reversed(rows)]
```

- [ ] **Step 4: Run** `uv run pytest tests/core/test_recorder.py tests/core/test_exchanges.py -q` → PASS
- [ ] **Step 5: Commit** `feat(core): record every HTTP exchange beneath the SDK`

---

### Task 5: Card fetching and signature verification

**Files:**
- Create: `core/connection/cards.py`
- Test: `tests/core/test_cards.py`

**Interfaces:**
- Consumes: `build_http_client`, `recording_scope`, `to_json`.
- Produces: `split_card_url(url) -> tuple[str, str | None]`; `CardResult(card, card_json, signature_status, signature_detail, exchange_ids)`; `async fetch_card(url, sink, *, card_path=None, agent_id=None) -> CardResult`; `async verify_card_signatures(card, http) -> tuple[SignatureStatus, str | None]`; `CardFetchError(Exception)` with `.cause: BaseException`.
- `SignatureStatus = Literal["verified", "invalid", "unsigned", "unverifiable"]`

- [ ] **Step 1: Failing tests** `tests/core/test_cards.py`

```python
import pytest

from a2a_workbench.core.connection.cards import CardFetchError, fetch_card, split_card_url


class Sink:
    def __init__(self):
        self.items = []

    async def __call__(self, ex):
        self.items.append(ex)


def test_split_card_url_base_only():
    assert split_card_url("https://h.dev/") == ("https://h.dev", None)


def test_split_card_url_full_well_known():
    assert split_card_url("https://h.dev/.well-known/agent-card.json") == (
        "https://h.dev", "/.well-known/agent-card.json")


def test_split_card_url_custom_json_path_keeps_prefix():
    assert split_card_url("https://h.dev/agents/x/card.json?v=1") == (
        "https://h.dev", "/agents/x/card.json?v=1")


def test_split_card_url_subpath_base():
    assert split_card_url("https://h.dev/agents/x") == ("https://h.dev/agents/x", None)


async def test_fetch_signed_card_verifies(zoo):
    sink = Sink()
    result = await fetch_card(zoo.base_url, sink)
    assert result.card.name == "Zoo agent"
    assert result.signature_status == "verified"
    assert result.card_json["name"] == "Zoo agent"
    assert len(result.exchange_ids) == 2  # card + jwks
    assert {e.operation for e in sink.items} == {"get_agent_card"}


async def test_fetch_unsigned_card(unsigned_zoo):
    result = await fetch_card(unsigned_zoo.base_url, Sink())
    assert result.signature_status == "unsigned"


async def test_tampered_card_is_invalid(zoo, monkeypatch):
    from a2a_workbench.core.connection import cards
    real = cards.A2ACardResolver.get_agent_card

    async def tampered(self, *a, **k):
        card = await real(self, *a, **k)
        card.description = "tampered"
        return card

    monkeypatch.setattr(cards.A2ACardResolver, "get_agent_card", tampered)
    result = await fetch_card(zoo.base_url, Sink())
    assert result.signature_status == "invalid"


async def test_fetch_card_unreachable_raises_card_error():
    with pytest.raises(CardFetchError):
        await fetch_card("http://127.0.0.1:1", Sink())
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** `core/connection/cards.py`

```python
"""Agent card resolution and signature verification through the A2A SDK."""

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from a2a.client import A2ACardResolver
from a2a.types import AgentCard
from a2a.utils.signing import SignatureVerificationError, create_signature_verifier
from jwt import PyJWKSet
from jwt.exceptions import PyJWKError, PyJWTError

from a2a_workbench.core.a2a_json import to_json
from a2a_workbench.core.connection.http import build_http_client
from a2a_workbench.core.connection.recorder import ExchangeSink, recording_scope

SignatureStatus = Literal["verified", "invalid", "unsigned", "unverifiable"]
ALLOWED_JWS_ALGORITHMS = [
    "ES256", "ES384", "ES512", "RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "EdDSA",
]


class CardFetchError(Exception):
    """Raised when an agent card cannot be fetched or parsed."""

    def __init__(self, message: str, cause: BaseException) -> None:
        super().__init__(message)
        self.cause = cause


@dataclass
class CardResult:
    """A resolved agent card with its verification outcome."""

    card: AgentCard
    card_json: dict[str, Any]
    signature_status: SignatureStatus
    signature_detail: str | None = None
    exchange_ids: list[str] = field(default_factory=list)


def split_card_url(url: str) -> tuple[str, str | None]:
    """Split a user-supplied URL into ``(base_url, card_path)``.

    A URL whose path ends in ``.json`` is treated as the card's own address;
    any other URL is the agent's base URL and the card path is left to the SDK
    default.
    """
    parts = urlsplit(url.strip())
    origin = urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")
    if parts.path.endswith(".json"):
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        return origin, path
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")).rstrip("/"), None


def _protected_header(protected: str) -> dict[str, Any]:
    padded = protected + "=" * (-len(protected) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


async def verify_card_signatures(
    card: AgentCard, http: httpx.AsyncClient
) -> tuple[SignatureStatus, str | None]:
    """Verify ``card.signatures`` using keys from each signature's ``jku`` JWKS URL.

    Returns ``unsigned`` without signatures, ``unverifiable`` when no key can be
    obtained, ``verified`` when at least one signature is valid, else ``invalid``.
    """
    if not card.signatures:
        return "unsigned", None
    keysets: dict[str, PyJWKSet] = {}
    for signature in card.signatures:
        try:
            jku = _protected_header(signature.protected).get("jku")
        except (ValueError, UnicodeDecodeError) as exc:
            return "invalid", f"malformed protected header: {exc}"
        if not jku or jku in keysets:
            continue
        try:
            response = await http.get(jku)
            response.raise_for_status()
            keysets[jku] = PyJWKSet.from_dict(response.json())
        except (httpx.HTTPError, ValueError, PyJWTError) as exc:
            return "unverifiable", f"could not load JWKS from {jku}: {exc}"
    if not keysets:
        return "unverifiable", "no signature names a jku key set URL"

    def key_provider(kid: str | None, jku: str | None) -> Any:
        keyset = keysets.get(jku or "")
        if keyset is None:
            raise PyJWKError(f"no key set loaded for {jku}")
        for key in keyset.keys:
            if kid is None or key.key_id == kid:
                return key
        raise PyJWKError(f"key {kid} not found in {jku}")

    try:
        create_signature_verifier(key_provider, ALLOWED_JWS_ALGORITHMS)(card)
    except SignatureVerificationError as exc:
        return "invalid", str(exc)
    return "verified", None


async def fetch_card(
    url: str, sink: ExchangeSink, *, card_path: str | None = None, agent_id: str | None = None
) -> CardResult:
    """Fetch, parse and verify the agent card addressed by ``url``.

    Raises:
        CardFetchError: if the card cannot be retrieved or parsed.
    """
    base_url, derived_path = split_card_url(url)
    path = card_path or derived_path
    with recording_scope("get_agent_card", agent_id=agent_id) as scope:
        async with build_http_client(sink) as http:
            resolver = A2ACardResolver(http, base_url)
            try:
                card = await resolver.get_agent_card(relative_card_path=path)
            except Exception as exc:
                raise CardFetchError(f"Could not load the agent card from {url}: {exc}", exc) from exc
            status, detail = await verify_card_signatures(card, http)
    return CardResult(card, to_json(card), status, detail, list(scope.exchange_ids))
```

- [ ] **Step 4: Run** `uv run pytest tests/core/test_cards.py -q` → PASS
- [ ] **Step 5: Commit** `feat(core): fetch agent cards and verify JWS signatures via the SDK`

---

### Task 6: Interface selection and SDK client construction

**Files:**
- Create: `core/connection/client.py`
- Test: `tests/core/test_client.py`

**Interfaces:**
- Produces: `SUPPORTED_BINDINGS = ("JSONRPC", "HTTP+JSON")`; `InterfaceNotFoundError`, `UnsupportedBindingError`; `select_interface(card, url: str | None) -> AgentInterface`; `card_for_interface(card, iface) -> AgentCard`; `async open_client(card, iface, sink, *, streaming: bool) -> Client` (caller closes it, preferably with `async with`).

- [ ] **Step 1: Failing tests** `tests/core/test_client.py`

```python
import pytest
from a2a.types import AgentCard, AgentInterface, Message, Part, Role, SendMessageRequest

from a2a_workbench.core.connection.cards import fetch_card
from a2a_workbench.core.connection.client import (
    InterfaceNotFoundError, UnsupportedBindingError, card_for_interface, open_client,
    select_interface,
)


def _card(*ifaces):
    return AgentCard(name="x", supported_interfaces=[
        AgentInterface(url=u, protocol_binding=b, protocol_version=v) for u, b, v in ifaces])


def test_select_default_prefers_jsonrpc_v1():
    card = _card(("g", "GRPC", "1.0"), ("r", "HTTP+JSON", "1.0"), ("j3", "JSONRPC", "0.3"),
                 ("j1", "JSONRPC", "1.0"))
    assert select_interface(card, None).url == "j1"


def test_select_by_url():
    card = _card(("j", "JSONRPC", "1.0"), ("r", "HTTP+JSON", "1.0"))
    assert select_interface(card, "r").protocol_binding == "HTTP+JSON"


def test_select_unknown_url_raises():
    with pytest.raises(InterfaceNotFoundError):
        select_interface(_card(("j", "JSONRPC", "1.0")), "nope")


def test_card_for_interface_keeps_only_chosen():
    card = _card(("j", "JSONRPC", "1.0"), ("r", "HTTP+JSON", "1.0"))
    narrowed = card_for_interface(card, card.supported_interfaces[1])
    assert [i.url for i in narrowed.supported_interfaces] == ["r"]
    assert len(card.supported_interfaces) == 2


async def test_grpc_not_supported_yet():
    card = _card(("g", "GRPC", "1.0"))
    with pytest.raises(UnsupportedBindingError):
        await open_client(card, card.supported_interfaces[0], lambda e: None, streaming=True)


@pytest.mark.parametrize("binding", ["JSONRPC", "HTTP+JSON"])
async def test_send_over_each_binding(zoo, binding):
    async def sink(_):
        return None
    result = await fetch_card(zoo.base_url, sink)
    iface = next(i for i in result.card.supported_interfaces if i.protocol_binding == binding)
    req = SendMessageRequest(message=Message(message_id="m", role=Role.ROLE_USER, parts=[Part(text="echo hi")]))
    async with await open_client(result.card, iface, sink, streaming=False) as client:
        events = [e async for e in client.send_message(req)]
    assert events[-1].task.status.state == 3  # TASK_STATE_COMPLETED
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** `core/connection/client.py`

```python
"""Construction of A2A SDK clients for a chosen agent interface."""

from a2a.client import Client, ClientConfig, ClientFactory
from a2a.types import AgentCard, AgentInterface

from a2a_workbench.core.connection.http import build_http_client
from a2a_workbench.core.connection.recorder import ExchangeSink

SUPPORTED_BINDINGS = ("JSONRPC", "HTTP+JSON")
_BINDING_PREFERENCE = ("JSONRPC", "HTTP+JSON", "GRPC")


class InterfaceNotFoundError(LookupError):
    """Raised when the card has no interface with the requested URL."""


class UnsupportedBindingError(ValueError):
    """Raised when an interface uses a protocol binding this build cannot speak."""


def _rank(iface: AgentInterface) -> tuple[int, int]:
    binding = (
        _BINDING_PREFERENCE.index(iface.protocol_binding)
        if iface.protocol_binding in _BINDING_PREFERENCE else len(_BINDING_PREFERENCE)
    )
    return binding, 0 if iface.protocol_version == "1.0" else 1


def select_interface(card: AgentCard, url: str | None) -> AgentInterface:
    """Return the interface at ``url``, or the preferred one when ``url`` is None.

    Preference: JSON-RPC, then HTTP+JSON, then gRPC; protocol version 1.0 first;
    otherwise card order.

    Raises:
        InterfaceNotFoundError: if ``url`` matches no interface, or the card has none.
    """
    interfaces = list(card.supported_interfaces)
    if url is not None:
        for iface in interfaces:
            if iface.url == url:
                return iface
        raise InterfaceNotFoundError(f"The agent card has no interface at {url}")
    if not interfaces:
        raise InterfaceNotFoundError("The agent card lists no supported interfaces")
    return min(interfaces, key=_rank)


def card_for_interface(card: AgentCard, iface: AgentInterface) -> AgentCard:
    """Return a copy of ``card`` whose only supported interface is ``iface``."""
    narrowed = AgentCard()
    narrowed.CopyFrom(card)
    del narrowed.supported_interfaces[:]
    narrowed.supported_interfaces.append(iface)
    return narrowed


async def open_client(
    card: AgentCard, iface: AgentInterface, sink: ExchangeSink, *, streaming: bool
) -> Client:
    """Return an SDK client bound to ``iface``, recording all traffic to ``sink``.

    Streaming is used only when ``streaming`` is true and the card declares it.

    Raises:
        UnsupportedBindingError: if ``iface`` uses a binding outside ``SUPPORTED_BINDINGS``.
    """
    if iface.protocol_binding not in SUPPORTED_BINDINGS:
        raise UnsupportedBindingError(f"{iface.protocol_binding} is not supported yet")
    config = ClientConfig(
        streaming=streaming,
        httpx_client=build_http_client(sink),
        supported_protocol_bindings=[iface.protocol_binding],
    )
    return ClientFactory(config).create(card_for_interface(card, iface))
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(core): select agent interfaces and build SDK clients`

---

### Task 7: Timeline events, artifact assembly, parts, options, error classification

**Files:**
- Create: `core/conversations/__init__.py`, `artifacts.py`, `timeline.py`, `parts.py`, `options.py`, `errors.py`
- Test: `tests/core/conversations/test_artifacts.py`, `test_timeline.py`, `test_parts.py`, `test_options.py`, `test_errors.py`

**Interfaces:**
- Produces:
  - `ArtifactAssembler.apply(event: TaskArtifactUpdateEvent) -> Artifact`, `.seed(task_id, artifact)`.
  - `TimelineEvent` (pydantic): `conversation_id: str, seq: int = 0, kind: EventKind, ts: datetime, task_id: str | None, context_id: str | None, exchange_id: str | None, data: dict`. `EventKind = Literal["user_message","message","task","status","artifact","error"]`.
  - `event_from_stream_response(resp, *, conversation_id, assembler, exchange_id) -> TimelineEvent`.
  - `TextPartInput`, `FilePartInput`, `DataPartInput`, `PartInput` (discriminated by `kind`); `BlobLookup = Callable[[str], Awaitable[tuple[bytes, str, str | None]]]`; `async build_part(p, blobs) -> Part`.
  - `SendOptions` (fields below); `build_request(message, options) -> SendMessageRequest`; `build_call_context(options) -> ClientCallContext | None`.
  - `classify_error(exc) -> dict` with keys `category`, `message`, and optionally `code`, `reason`, `http_status`, `data`.

- [ ] **Step 1: Failing tests**

`test_artifacts.py`:
```python
from a2a.types import Artifact, Part, TaskArtifactUpdateEvent

from a2a_workbench.core.conversations.artifacts import ArtifactAssembler


def _ev(text, append, last, aid="a"):
    return TaskArtifactUpdateEvent(task_id="t", artifact=Artifact(artifact_id=aid, name="n", parts=[Part(text=text)]),
                                   append=append, last_chunk=last)


def test_append_concatenates_parts_in_order():
    asm = ArtifactAssembler()
    asm.apply(_ev("a", False, False))
    asm.apply(_ev("b", True, False))
    out = asm.apply(_ev("c", True, True))
    assert [p.text for p in out.parts] == ["a", "b", "c"]
    assert out.name == "n"


def test_non_append_replaces():
    asm = ArtifactAssembler()
    asm.apply(_ev("a", False, False))
    assert [p.text for p in asm.apply(_ev("z", False, True)).parts] == ["z"]


def test_append_without_prior_starts_new():
    assert [p.text for p in ArtifactAssembler().apply(_ev("x", True, True)).parts] == ["x"]


def test_artifacts_are_isolated_per_id():
    asm = ArtifactAssembler()
    asm.apply(_ev("a", False, False, "1"))
    assert [p.text for p in asm.apply(_ev("b", True, False, "2")).parts] == ["b"]


def test_seed_then_append():
    asm = ArtifactAssembler()
    asm.seed("t", Artifact(artifact_id="a", parts=[Part(text="s")]))
    assert [p.text for p in asm.apply(_ev("x", True, True)).parts] == ["s", "x"]
```

`test_timeline.py`:
```python
from a2a.types import (
    Artifact, Message, Part, Role, StreamResponse, Task, TaskArtifactUpdateEvent, TaskState,
    TaskStatus, TaskStatusUpdateEvent,
)

from a2a_workbench.core.conversations.artifacts import ArtifactAssembler
from a2a_workbench.core.conversations.timeline import event_from_stream_response


def _conv(resp):
    return event_from_stream_response(resp, conversation_id="c", assembler=ArtifactAssembler(), exchange_id="e")


def test_task_event():
    ev = _conv(StreamResponse(task=Task(id="t", context_id="x", status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED))))
    assert (ev.kind, ev.task_id, ev.context_id, ev.exchange_id) == ("task", "t", "x", "e")
    assert ev.data["state"] == "submitted" and ev.data["task"]["id"] == "t"


def test_message_event():
    ev = _conv(StreamResponse(message=Message(message_id="m", context_id="x", role=Role.ROLE_AGENT, parts=[Part(text="hi")])))
    assert ev.kind == "message" and ev.task_id is None and ev.context_id == "x"
    assert ev.data["message"]["parts"] == [{"text": "hi"}]


def test_status_event():
    ev = _conv(StreamResponse(status_update=TaskStatusUpdateEvent(
        task_id="t", context_id="x", status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED))))
    assert ev.kind == "status" and ev.data["state"] == "input_required"


def test_artifact_event_includes_assembled():
    asm = ArtifactAssembler()
    r1 = StreamResponse(artifact_update=TaskArtifactUpdateEvent(task_id="t", context_id="x",
         artifact=Artifact(artifact_id="a", parts=[Part(text="1")])))
    r2 = StreamResponse(artifact_update=TaskArtifactUpdateEvent(task_id="t", context_id="x", append=True, last_chunk=True,
         artifact=Artifact(artifact_id="a", parts=[Part(text="2")])))
    event_from_stream_response(r1, conversation_id="c", assembler=asm, exchange_id=None)
    ev = event_from_stream_response(r2, conversation_id="c", assembler=asm, exchange_id=None)
    assert ev.data["append"] is True and ev.data["last_chunk"] is True
    assert ev.data["assembled"]["parts"] == [{"text": "1"}, {"text": "2"}]
```

`test_parts.py`:
```python
import base64

import pytest
from pydantic import TypeAdapter, ValidationError

from a2a_workbench.core.conversations.parts import PartInput, build_part

adapter = TypeAdapter(PartInput)


async def _blobs(blob_id):
    return b"\x89PNG", "image/png", "p.png"


async def test_text_part():
    p = await build_part(adapter.validate_python({"kind": "text", "text": "hi", "metadata": {"k": 1}}), _blobs)
    assert p.text == "hi" and p.metadata["k"] == 1


async def test_file_part_from_blob_is_raw():
    p = await build_part(adapter.validate_python({"kind": "file", "blob_id": "b1"}), _blobs)
    assert p.raw == b"\x89PNG" and p.media_type == "image/png" and p.filename == "p.png"


async def test_file_part_from_url():
    p = await build_part(adapter.validate_python(
        {"kind": "file", "url": "https://x/y.pdf", "media_type": "application/pdf"}), _blobs)
    assert p.url == "https://x/y.pdf" and p.media_type == "application/pdf"


async def test_file_part_inline_base64():
    p = await build_part(adapter.validate_python(
        {"kind": "file", "raw_base64": base64.b64encode(b"ab").decode(), "media_type": "text/plain"}), _blobs)
    assert p.raw == b"ab"


async def test_data_part():
    p = await build_part(adapter.validate_python({"kind": "data", "data": {"a": [1, 2]}}), _blobs)
    assert p.data.struct_value.fields["a"].list_value.values[1].number_value == 2


def test_file_part_requires_exactly_one_source():
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "file"})
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "file", "url": "u", "blob_id": "b"})
```

`test_options.py`:
```python
from a2a.types import Message

from a2a_workbench.core.conversations.options import SendOptions, build_call_context, build_request


def test_defaults_leave_optional_fields_unset():
    req = build_request(Message(message_id="m"), SendOptions())
    assert not req.configuration.HasField("history_length")
    assert req.configuration.return_immediately is False
    assert list(req.configuration.accepted_output_modes) == []
    assert build_call_context(SendOptions()) is None


def test_every_option_is_mapped():
    opts = SendOptions(return_immediately=True, accepted_output_modes=["text/plain"], history_length=3,
                       extensions=["https://e/1", "https://e/2"], message_metadata={"a": 1},
                       request_metadata={"b": 2}, reference_task_ids=["t0"])
    req = build_request(Message(message_id="m"), opts)
    assert req.configuration.history_length == 3
    assert req.configuration.return_immediately is True
    assert list(req.configuration.accepted_output_modes) == ["text/plain"]
    assert req.message.metadata["a"] == 1 and req.metadata["b"] == 2
    assert list(req.message.reference_task_ids) == ["t0"]
    assert list(req.message.extensions) == ["https://e/1", "https://e/2"]
    ctx = build_call_context(opts)
    assert ctx.service_parameters["A2A-Extensions"] == "https://e/1,https://e/2"
```

`test_errors.py`:
```python
import httpx
from a2a.client import A2AClientError, A2AClientTimeoutError
from a2a.utils.errors import TaskNotCancelableError

from a2a_workbench.core.conversations.errors import classify_error


def _wrapped(status):
    req = httpx.Request("POST", "http://x")
    try:
        try:
            httpx.Response(status, request=req).raise_for_status()
        except httpx.HTTPStatusError as e:
            raise A2AClientError(f"HTTP Error {status}") from e
    except A2AClientError as outer:
        return outer


def test_auth_from_401():
    assert classify_error(_wrapped(401))["category"] == "auth"


def test_protocol_from_500():
    out = classify_error(_wrapped(500))
    assert out["category"] == "protocol" and out["http_status"] == 500


def test_transport_from_connect_error():
    try:
        try:
            raise httpx.ConnectError("refused")
        except httpx.ConnectError as e:
            raise A2AClientError("Network communication error") from e
    except A2AClientError as exc:
        assert classify_error(exc)["category"] == "transport"


def test_transport_from_timeout():
    assert classify_error(A2AClientTimeoutError("t"))["category"] == "transport"


def test_protocol_error_has_code_and_reason():
    out = classify_error(TaskNotCancelableError())
    assert out == {"category": "protocol", "message": "Task cannot be canceled", "code": -32002,
                   "reason": "TASK_NOT_CANCELABLE", "data": None}


def test_unknown_is_workbench():
    assert classify_error(RuntimeError("boom"))["category"] == "workbench"
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement**

`artifacts.py`:
```python
"""Reassembly of streamed artifacts."""

from a2a.types import Artifact, TaskArtifactUpdateEvent


class ArtifactAssembler:
    """Builds complete artifacts from ``TaskArtifactUpdateEvent`` chunks.

    A chunk with ``append`` set extends the parts of the artifact with the same
    task and artifact id; any other chunk replaces it.
    """

    def __init__(self) -> None:
        self._artifacts: dict[tuple[str, str], Artifact] = {}

    def seed(self, task_id: str, artifact: Artifact) -> None:
        """Record an artifact already known from a Task snapshot."""
        copy = Artifact()
        copy.CopyFrom(artifact)
        self._artifacts[(task_id, artifact.artifact_id)] = copy

    def apply(self, event: TaskArtifactUpdateEvent) -> Artifact:
        """Merge ``event`` into the assembled artifact and return the result."""
        key = (event.task_id, event.artifact.artifact_id)
        current = self._artifacts.get(key)
        merged = Artifact()
        if event.append and current is not None:
            merged.CopyFrom(current)
            merged.parts.extend(event.artifact.parts)
            if event.artifact.name:
                merged.name = event.artifact.name
            if event.artifact.description:
                merged.description = event.artifact.description
            merged.metadata.update(event.artifact.metadata)
            merged.extensions.extend(e for e in event.artifact.extensions if e not in merged.extensions)
        else:
            merged.CopyFrom(event.artifact)
        self._artifacts[key] = merged
        return merged
```

`timeline.py`:
```python
"""Normalized conversation timeline events."""

from datetime import UTC, datetime
from typing import Any, Literal

from a2a.types import StreamResponse
from pydantic import BaseModel, Field

from a2a_workbench.core.a2a_json import state_name, to_json
from a2a_workbench.core.conversations.artifacts import ArtifactAssembler

EventKind = Literal["user_message", "message", "task", "status", "artifact", "error"]


class TimelineEvent(BaseModel):
    """One entry of a conversation timeline, in a binding-independent shape."""

    conversation_id: str
    seq: int = 0
    kind: EventKind
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    task_id: str | None = None
    context_id: str | None = None
    exchange_id: str | None = None
    data: dict[str, Any]


def event_from_stream_response(
    resp: StreamResponse, *, conversation_id: str, assembler: ArtifactAssembler,
    exchange_id: str | None,
) -> TimelineEvent:
    """Convert one SDK ``StreamResponse`` into a ``TimelineEvent``.

    Artifact updates are merged through ``assembler``; the event carries both the
    received chunk and the assembled artifact.
    """
    payload = resp.WhichOneof("payload")
    common = {"conversation_id": conversation_id, "exchange_id": exchange_id}
    if payload == "task":
        task = resp.task
        for artifact in task.artifacts:
            assembler.seed(task.id, artifact)
        return TimelineEvent(kind="task", task_id=task.id, context_id=task.context_id or None,
                             data={"task": to_json(task), "state": state_name(task.status.state)}, **common)
    if payload == "message":
        msg = resp.message
        return TimelineEvent(kind="message", task_id=msg.task_id or None, context_id=msg.context_id or None,
                             data={"message": to_json(msg)}, **common)
    if payload == "status_update":
        su = resp.status_update
        return TimelineEvent(kind="status", task_id=su.task_id, context_id=su.context_id or None,
                             data={"state": state_name(su.status.state), "status": to_json(su.status),
                                   "metadata": to_json(su.metadata) if su.metadata.fields else None},
                             **common)
    if payload == "artifact_update":
        au = resp.artifact_update
        assembled = assembler.apply(au)
        return TimelineEvent(kind="artifact", task_id=au.task_id, context_id=au.context_id or None,
                             data={"artifact": to_json(au.artifact), "append": au.append,
                                   "last_chunk": au.last_chunk, "assembled": to_json(assembled)},
                             **common)
    raise ValueError(f"StreamResponse has no payload: {payload!r}")
```

`parts.py`:
```python
"""User-supplied message parts and their conversion to A2A ``Part`` objects."""

import base64
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from a2a.types import Part
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Value
from pydantic import BaseModel, Field, model_validator

BlobLookup = Callable[[str], Awaitable[tuple[bytes, str, str | None]]]


class TextPartInput(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    media_type: str | None = None
    metadata: dict[str, Any] | None = None


class FilePartInput(BaseModel):
    """A file given by uploaded blob id, inline base64 bytes, or URL (exactly one)."""

    kind: Literal["file"] = "file"
    blob_id: str | None = None
    raw_base64: str | None = None
    url: str | None = None
    media_type: str | None = None
    filename: str | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "FilePartInput":
        if sum(v is not None for v in (self.blob_id, self.raw_base64, self.url)) != 1:
            raise ValueError("exactly one of blob_id, raw_base64 or url is required")
        return self


class DataPartInput(BaseModel):
    kind: Literal["data"] = "data"
    data: Any
    media_type: str | None = None
    metadata: dict[str, Any] | None = None


PartInput = Annotated[TextPartInput | FilePartInput | DataPartInput, Field(discriminator="kind")]


async def build_part(part: TextPartInput | FilePartInput | DataPartInput, blobs: BlobLookup) -> Part:
    """Return the A2A ``Part`` for ``part``, loading uploaded bytes through ``blobs``."""
    out = Part()
    if part.metadata:
        out.metadata.update(part.metadata)
    if isinstance(part, TextPartInput):
        out.text = part.text
        if part.media_type:
            out.media_type = part.media_type
        return out
    if isinstance(part, DataPartInput):
        out.data.CopyFrom(ParseDict(part.data, Value()))
        if part.media_type:
            out.media_type = part.media_type
        return out
    media_type, filename = part.media_type, part.filename
    if part.blob_id is not None:
        raw, blob_type, blob_name = await blobs(part.blob_id)
        out.raw = raw
        media_type, filename = media_type or blob_type, filename or blob_name
    elif part.raw_base64 is not None:
        out.raw = base64.b64decode(part.raw_base64)
    else:
        out.url = part.url or ""
    if media_type:
        out.media_type = media_type
    if filename:
        out.filename = filename
    return out
```

`options.py`:
```python
"""Per-message send options and their mapping onto SDK request objects."""

from typing import Any

from a2a.client import ClientCallContext
from a2a.client.service_parameters import ServiceParametersFactory, with_a2a_extensions
from a2a.types import Message, SendMessageConfiguration, SendMessageRequest
from pydantic import BaseModel, Field


class SendOptions(BaseModel):
    """Every client-controllable aspect of a SendMessage / SendStreamingMessage call."""

    stream: bool = True
    return_immediately: bool = False
    accepted_output_modes: list[str] = Field(default_factory=list)
    history_length: int | None = Field(default=None, ge=0)
    extensions: list[str] = Field(default_factory=list)
    message_metadata: dict[str, Any] | None = None
    request_metadata: dict[str, Any] | None = None
    reference_task_ids: list[str] = Field(default_factory=list)
    task_id: str | None = None
    context_id: str | None = None
    interface_url: str | None = None


def build_request(message: Message, options: SendOptions) -> SendMessageRequest:
    """Return a ``SendMessageRequest`` for ``message`` configured by ``options``.

    Message-level fields (metadata, extensions, reference task ids) are set on a
    copy of ``message``.
    """
    msg = Message()
    msg.CopyFrom(message)
    if options.message_metadata:
        msg.metadata.update(options.message_metadata)
    msg.extensions.extend(options.extensions)
    msg.reference_task_ids.extend(options.reference_task_ids)
    config = SendMessageConfiguration(
        accepted_output_modes=options.accepted_output_modes,
        return_immediately=options.return_immediately,
    )
    if options.history_length is not None:
        config.history_length = options.history_length
    request = SendMessageRequest(message=msg, configuration=config)
    if options.request_metadata:
        request.metadata.update(options.request_metadata)
    return request


def build_call_context(options: SendOptions) -> ClientCallContext | None:
    """Return a call context that activates ``options.extensions``, or None."""
    if not options.extensions:
        return None
    params = ServiceParametersFactory.create([with_a2a_extensions(options.extensions)])
    return ClientCallContext(service_parameters=params)
```

`errors.py`:
```python
"""Classification of failures raised while talking to an agent."""

from collections.abc import Iterator
from typing import Any

import httpx
from a2a.client import A2AClientError, A2AClientTimeoutError
from a2a.utils.errors import A2A_ERROR_MAPPING, JSON_RPC_ERROR_CODE_MAP, A2AError


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify_error(exc: BaseException) -> dict[str, Any]:
    """Return ``{"category", "message", ...}`` describing ``exc``.

    Categories: ``auth`` (HTTP 401/403), ``transport`` (network, TLS, timeouts),
    ``protocol`` (A2A errors, non-auth HTTP errors, malformed responses) and
    ``workbench`` (anything else).
    """
    chain = list(_chain(exc))
    status = next((e.response.status_code for e in chain if isinstance(e, httpx.HTTPStatusError)), None)
    if status in (401, 403):
        return {"category": "auth", "message": str(exc), "http_status": status}
    if any(isinstance(e, (A2AClientTimeoutError, httpx.TransportError)) for e in chain):
        return {"category": "transport", "message": str(exc)}
    a2a = next((e for e in chain if isinstance(e, A2AError) and not isinstance(e, A2AClientError)), None)
    if a2a is not None:
        mapping = A2A_ERROR_MAPPING.get(type(a2a))
        return {"category": "protocol", "message": a2a.message,
                "code": JSON_RPC_ERROR_CODE_MAP.get(type(a2a)),
                "reason": mapping.reason if mapping else None, "data": a2a.data}
    if isinstance(exc, A2AClientError) or status is not None:
        out: dict[str, Any] = {"category": "protocol", "message": str(exc)}
        if status is not None:
            out["http_status"] = status
        return out
    return {"category": "workbench", "message": f"{type(exc).__name__}: {exc}"}
```

- [ ] **Step 4: Run** `uv run pytest tests/core/conversations -q` → PASS
- [ ] **Step 5: Commit** `feat(core): timeline events, artifact assembly, parts, options and error classes`

---

### Task 8: Blob, agent and conversation services, Workbench container

**Files:**
- Create: `core/blobs.py`, `core/registry/__init__.py`, `core/registry/service.py`, `core/conversations/service.py`, `core/workbench.py`
- Test: `tests/core/test_blobs.py`, `tests/core/test_agents.py`, `tests/core/test_conversations.py`, `tests/core/conftest.py`

**Interfaces:**
- Produces:
  - `BlobService(db, max_bytes)`: `async put(data, media_type, filename) -> BlobOut`, `async lookup(blob_id) -> tuple[bytes, str, str | None]`, `async get(blob_id) -> Blob | None`; `BlobTooLargeError`, `BlobNotFoundError`.
  - `InterfaceOut(url, binding, protocol_version, tenant, supported)`, `AgentOut(id, name, base_url, card_path, card, signature_status, signature_detail, selected_interface_url, interfaces, created_at, updated_at)`, `CardPreview(card, signature_status, signature_detail, interfaces, exchange_ids)`.
  - `AgentService(db, sink)`: `preview(url)`, `add(url, card_path=None)`, `list()`, `get(id)`, `resolve(ref)`, `remove(id)`, `refresh_card(id)`, `set_interface(id, url)`; `AgentNotFoundError`, `AgentExistsError`.
  - `ConversationOut(id, agent_id, title, origin, context_id, task_id, task_state, last_seq, created_at, updated_at)`.
  - `ConversationService(db, bus, sink, blobs)`: `create(agent_id, *, title=None, origin="chat")`, `get(id)`, `list_for_agent(agent_id)`, `events(id, after_seq=0)`, `send(id, parts, options) -> AsyncIterator[TimelineEvent]`, `cancel(id) -> AsyncIterator[TimelineEvent]`; `ConversationNotFoundError`. Publishes `{"type": "event", "event": <TimelineEvent json>}` to `conversation:<id>`.
  - `Workbench(settings)`: attributes `settings, db, bus, exchanges, blobs, agents, conversations`; `async start()`, `async close()`; `Workbench.open(settings)` async context manager.

- [ ] **Step 1: Failing tests**

`tests/core/conftest.py`:
```python
import pytest

from a2a_workbench.core.config import Settings
from a2a_workbench.core.workbench import Workbench


@pytest.fixture
async def wb():
    async with Workbench.open(Settings()) as workbench:
        yield workbench
```

`tests/core/test_blobs.py`:
```python
import pytest

from a2a_workbench.core.blobs import BlobNotFoundError, BlobTooLargeError


async def test_put_and_lookup(wb):
    out = await wb.blobs.put(b"abc", "text/plain", "a.txt")
    assert out.size == 3
    assert await wb.blobs.lookup(out.id) == (b"abc", "text/plain", "a.txt")


async def test_too_large(wb):
    wb.blobs.max_bytes = 2
    with pytest.raises(BlobTooLargeError):
        await wb.blobs.put(b"abc", "text/plain", None)


async def test_missing(wb):
    with pytest.raises(BlobNotFoundError):
        await wb.blobs.lookup("nope")
```

`tests/core/test_agents.py`:
```python
import pytest

from a2a_workbench.core.connection.cards import CardFetchError
from a2a_workbench.core.registry.service import AgentExistsError, AgentNotFoundError


async def test_add_list_get_resolve_remove(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    assert agent.name == "Zoo agent" and agent.signature_status == "verified"
    assert agent.selected_interface_url == f"{zoo.base_url}/a2a"
    assert {i.binding for i in agent.interfaces} == {"JSONRPC", "HTTP+JSON"}
    assert all(i.supported for i in agent.interfaces)
    assert [a.id for a in await wb.agents.list()] == [agent.id]
    assert (await wb.agents.resolve("Zoo agent")).id == agent.id
    assert (await wb.agents.resolve(zoo.base_url)).id == agent.id
    await wb.agents.remove(agent.id)
    with pytest.raises(AgentNotFoundError):
        await wb.agents.get(agent.id)


async def test_add_twice_raises(wb, zoo):
    await wb.agents.add(zoo.base_url)
    with pytest.raises(AgentExistsError):
        await wb.agents.add(zoo.base_url + "/")


async def test_add_unreachable(wb):
    with pytest.raises(CardFetchError):
        await wb.agents.add("http://127.0.0.1:1")
    assert await wb.agents.list() == []


async def test_set_interface(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    updated = await wb.agents.set_interface(agent.id, f"{zoo.base_url}/v1")
    assert updated.selected_interface_url == f"{zoo.base_url}/v1"


async def test_preview_does_not_persist(wb, zoo):
    preview = await wb.agents.preview(zoo.base_url)
    assert preview.card["name"] == "Zoo agent"
    assert await wb.agents.list() == []
```

`tests/core/test_conversations.py`:
```python
import pytest

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import DataPartInput, FilePartInput, TextPartInput


async def _send(wb, conv_id, text, **opts):
    return [e async for e in wb.conversations.send(conv_id, [TextPartInput(text=text)], SendOptions(**opts))]


@pytest.fixture
async def conv(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    return await wb.conversations.create(agent.id)


async def test_streaming_echo_produces_ordered_events(wb, conv):
    events = await _send(wb, conv.id, "stream")
    kinds = [e.kind for e in events]
    assert kinds[0] == "user_message" and kinds[1] == "task"
    assert kinds.count("artifact") == 4
    assert events[-1].kind == "status" and events[-1].data["state"] == "completed"
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert events[-2].data["assembled"]["parts"][-1] == {"text": "pieces."}
    assert all(e.exchange_id for e in events[1:])
    stored = await wb.conversations.events(conv.id)
    assert [e.seq for e in stored] == [e.seq for e in events]
    exchanges = await wb.exchanges.list(conversation_id=conv.id)
    assert exchanges[-1]["operation"] == "send_message" and exchanges[-1]["frame_count"] == len(events) - 1


async def test_non_streaming_send(wb, conv):
    events = await _send(wb, conv.id, "echo hi", stream=False)
    assert [e.kind for e in events] == ["user_message", "task"]
    assert events[-1].data["state"] == "completed"


async def test_direct_message_reply(wb, conv):
    events = await _send(wb, conv.id, "message yo")
    assert events[-1].kind == "message"
    assert events[-1].data["message"]["parts"][0]["text"] == "Direct reply: yo"


async def test_reply_to_input_required_continues_task(wb, conv):
    first = await _send(wb, conv.id, "ask")
    assert first[-1].data["state"] == "input_required"
    task_id = first[-1].task_id
    assert (await wb.conversations.get(conv.id)).task_state == "input_required"
    second = await _send(wb, conv.id, "B")
    assert second[0].data["message"]["taskId"] == task_id
    assert second[-1].data["state"] == "completed" and second[-1].task_id == task_id


async def test_message_after_completion_starts_new_task_same_context(wb, conv):
    first = await _send(wb, conv.id, "echo one")
    second = await _send(wb, conv.id, "echo two")
    assert second[0].data["message"].get("taskId") is None
    assert second[0].data["message"]["contextId"] == first[1].context_id
    assert second[1].task_id != first[1].task_id


async def test_options_reach_the_agent(wb, conv):
    events = await _send(wb, conv.id, "inspect", accepted_output_modes=["application/json"], history_length=2,
                         extensions=["https://example.com/ext/x"], message_metadata={"k": "v"})
    report = next(e for e in events if e.kind == "artifact").data["assembled"]["parts"][0]["data"]
    assert report["configuration"]["acceptedOutputModes"] == ["application/json"]
    assert report["configuration"]["historyLength"] == 2
    assert report["requestedExtensions"] == ["https://example.com/ext/x"]
    assert report["message"]["metadata"] == {"k": "v"}


async def test_file_and_data_parts_are_sent(wb, conv):
    blob = await wb.blobs.put(b"hello", "text/plain", "h.txt")
    parts = [TextPartInput(text="inspect"), FilePartInput(blob_id=blob.id), DataPartInput(data={"n": 1})]
    events = [e async for e in wb.conversations.send(conv.id, parts, SendOptions())]
    sent = events[0].data["message"]["parts"]
    assert sent[1]["filename"] == "h.txt" and sent[1]["mediaType"] == "text/plain"
    assert sent[2]["data"] == {"n": 1}


async def test_cancel_running_task(wb, conv):
    events = await _send(wb, conv.id, "slow 30", return_immediately=True, stream=False)
    assert (await wb.conversations.get(conv.id)).task_state in {"submitted", "working"}
    cancel_events = [e async for e in wb.conversations.cancel(conv.id)]
    assert cancel_events[-1].data["state"] == "canceled"


async def test_unreachable_agent_emits_transport_error(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    from sqlalchemy import update
    from a2a_workbench.core.store.models import Agent
    card = dict(agent.card)
    card["supportedInterfaces"] = [{"url": "http://127.0.0.1:1/a2a", "protocolBinding": "JSONRPC",
                                    "protocolVersion": "1.0"}]
    async with wb.db.sessions() as s:
        await s.execute(update(Agent).where(Agent.id == agent.id).values(
            card=card, selected_interface_url="http://127.0.0.1:1/a2a"))
        await s.commit()
    events = await _send(wb, conv.id, "echo")
    assert events[-1].kind == "error" and events[-1].data["category"] == "transport"
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement**

`core/blobs.py`:
```python
"""Storage of user-uploaded files."""

from pydantic import BaseModel

from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import Blob


class BlobTooLargeError(ValueError):
    """Raised when an upload exceeds the configured size limit."""


class BlobNotFoundError(LookupError):
    """Raised when a blob id does not exist."""


class BlobOut(BaseModel):
    id: str
    media_type: str
    filename: str | None
    size: int


class BlobService:
    """Stores uploaded bytes in the database, up to ``max_bytes`` each."""

    def __init__(self, db: Database, max_bytes: int) -> None:
        self._db = db
        self.max_bytes = max_bytes

    async def put(self, data: bytes, media_type: str, filename: str | None) -> BlobOut:
        """Store ``data`` and return its descriptor.

        Raises:
            BlobTooLargeError: if ``data`` is longer than ``max_bytes``.
        """
        if len(data) > self.max_bytes:
            raise BlobTooLargeError(f"file is larger than {self.max_bytes} bytes")
        blob = Blob(media_type=media_type or "application/octet-stream", filename=filename,
                    size=len(data), data=data)
        async with self._db.sessions() as session:
            session.add(blob)
            await session.commit()
        return BlobOut(id=blob.id, media_type=blob.media_type, filename=filename, size=blob.size)

    async def get(self, blob_id: str) -> Blob | None:
        """Return the stored blob, or None."""
        async with self._db.sessions() as session:
            return await session.get(Blob, blob_id)

    async def lookup(self, blob_id: str) -> tuple[bytes, str, str | None]:
        """Return ``(data, media_type, filename)`` of a blob.

        Raises:
            BlobNotFoundError: if the blob does not exist.
        """
        blob = await self.get(blob_id)
        if blob is None:
            raise BlobNotFoundError(blob_id)
        return blob.data, blob.media_type, blob.filename
```

`core/registry/service.py`:
```python
"""Registered agents."""

from datetime import datetime
from typing import Any

from a2a.types import AgentCard
from pydantic import BaseModel
from sqlalchemy import delete, select

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.connection.cards import CardResult, SignatureStatus, fetch_card, split_card_url
from a2a_workbench.core.connection.client import SUPPORTED_BINDINGS, select_interface
from a2a_workbench.core.connection.recorder import ExchangeSink
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import (
    DEFAULT_WORKSPACE_ID, Agent, Conversation, ExchangeRow, TimelineEventRow,
)


class AgentNotFoundError(LookupError):
    """Raised when no agent matches an id or reference."""


class AgentExistsError(ValueError):
    """Raised when an agent with the same base URL and card path is registered."""


class InterfaceOut(BaseModel):
    url: str
    binding: str
    protocol_version: str
    tenant: str
    supported: bool


class AgentOut(BaseModel):
    id: str
    name: str
    base_url: str
    card_path: str | None
    card: dict[str, Any]
    signature_status: str
    signature_detail: str | None
    selected_interface_url: str | None
    interfaces: list[InterfaceOut]
    created_at: datetime
    updated_at: datetime


class CardPreview(BaseModel):
    card: dict[str, Any]
    signature_status: SignatureStatus
    signature_detail: str | None
    interfaces: list[InterfaceOut]
    default_interface_url: str | None
    exchange_ids: list[str]


def interfaces_of(card: AgentCard) -> list[InterfaceOut]:
    """Return the card's interfaces with a flag for bindings this build supports."""
    return [
        InterfaceOut(url=i.url, binding=i.protocol_binding, protocol_version=i.protocol_version,
                     tenant=i.tenant, supported=i.protocol_binding in SUPPORTED_BINDINGS)
        for i in card.supported_interfaces
    ]


def _default_interface(card: AgentCard) -> str | None:
    supported = [i for i in card.supported_interfaces if i.protocol_binding in SUPPORTED_BINDINGS]
    if not supported:
        return None
    narrowed = AgentCard(supported_interfaces=supported)
    return select_interface(narrowed, None).url


def _out(agent: Agent) -> AgentOut:
    return AgentOut(
        id=agent.id, name=agent.name, base_url=agent.base_url, card_path=agent.card_path,
        card=agent.card, signature_status=agent.signature_status,
        signature_detail=agent.signature_detail, selected_interface_url=agent.selected_interface_url,
        interfaces=interfaces_of(card_from_json(agent.card)),
        created_at=agent.created_at, updated_at=agent.updated_at,
    )


class AgentService:
    """Registers agents by URL and keeps their cards."""

    def __init__(self, db: Database, sink: ExchangeSink) -> None:
        self._db = db
        self._sink = sink

    async def preview(self, url: str) -> CardPreview:
        """Fetch and verify the card at ``url`` without registering it."""
        result = await fetch_card(url, self._sink)
        return CardPreview(card=result.card_json, signature_status=result.signature_status,
                           signature_detail=result.signature_detail,
                           interfaces=interfaces_of(result.card),
                           default_interface_url=_default_interface(result.card),
                           exchange_ids=result.exchange_ids)

    async def add(self, url: str, card_path: str | None = None) -> AgentOut:
        """Fetch the card at ``url`` and register the agent.

        Raises:
            AgentExistsError: if the same base URL and card path is registered.
            CardFetchError: if the card cannot be loaded.
        """
        base_url, derived_path = split_card_url(url)
        path = card_path or derived_path
        async with self._db.sessions() as session:
            existing = await session.execute(
                select(Agent).where(Agent.base_url == base_url, Agent.card_path.is_(path)
                                    if path is None else Agent.card_path == path))
            if existing.scalar_one_or_none():
                raise AgentExistsError(f"{url} is already registered")
        result = await fetch_card(url, self._sink, card_path=card_path)
        agent = Agent(workspace_id=DEFAULT_WORKSPACE_ID, name=result.card.name or base_url,
                      base_url=base_url, card_path=path, card=result.card_json,
                      signature_status=result.signature_status,
                      signature_detail=result.signature_detail,
                      selected_interface_url=_default_interface(result.card))
        async with self._db.sessions() as session:
            session.add(agent)
            await session.commit()
        return _out(agent)

    async def list(self) -> list[AgentOut]:
        """Return all agents, oldest first."""
        async with self._db.sessions() as session:
            rows = (await session.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
        return [_out(a) for a in rows]

    async def _row(self, agent_id: str) -> Agent:
        async with self._db.sessions() as session:
            agent = await session.get(Agent, agent_id)
        if agent is None:
            raise AgentNotFoundError(agent_id)
        return agent

    async def get(self, agent_id: str) -> AgentOut:
        """Return one agent.

        Raises:
            AgentNotFoundError: if it does not exist.
        """
        return _out(await self._row(agent_id))

    async def row(self, agent_id: str) -> Agent:
        """Return the stored agent row.

        Raises:
            AgentNotFoundError: if it does not exist.
        """
        return await self._row(agent_id)

    async def resolve(self, ref: str) -> AgentOut:
        """Return the agent whose id, name or base URL equals ``ref``.

        Raises:
            AgentNotFoundError: if none matches.
        """
        base_url, _ = split_card_url(ref)
        for agent in await self.list():
            if ref in (agent.id, agent.name) or agent.base_url == base_url:
                return agent
        raise AgentNotFoundError(ref)

    async def remove(self, agent_id: str) -> None:
        """Delete an agent with its conversations, events and exchanges.

        Raises:
            AgentNotFoundError: if it does not exist.
        """
        await self._row(agent_id)
        async with self._db.sessions() as session:
            conv_ids = select(Conversation.id).where(Conversation.agent_id == agent_id)
            await session.execute(delete(TimelineEventRow).where(TimelineEventRow.conversation_id.in_(conv_ids)))
            await session.execute(delete(Conversation).where(Conversation.agent_id == agent_id))
            await session.execute(delete(ExchangeRow).where(ExchangeRow.agent_id == agent_id))
            await session.execute(delete(Agent).where(Agent.id == agent_id))
            await session.commit()

    async def refresh_card(self, agent_id: str) -> AgentOut:
        """Re-fetch the agent's card, keeping the selected interface when still listed."""
        agent = await self._row(agent_id)
        result: CardResult = await fetch_card(agent.base_url, self._sink, card_path=agent.card_path,
                                              agent_id=agent_id)
        urls = {i.url for i in result.card.supported_interfaces}
        async with self._db.sessions() as session:
            row = await session.get(Agent, agent_id)
            assert row is not None
            row.card = result.card_json
            row.name = result.card.name or row.name
            row.signature_status = result.signature_status
            row.signature_detail = result.signature_detail
            if row.selected_interface_url not in urls:
                row.selected_interface_url = _default_interface(result.card)
            await session.commit()
            return _out(row)

    async def set_interface(self, agent_id: str, url: str) -> AgentOut:
        """Select the interface used for future calls.

        Raises:
            InterfaceNotFoundError: if the card has no interface at ``url``.
        """
        agent = await self._row(agent_id)
        select_interface(card_from_json(agent.card), url)
        async with self._db.sessions() as session:
            row = await session.get(Agent, agent_id)
            assert row is not None
            row.selected_interface_url = url
            await session.commit()
            return _out(row)
```

`core/conversations/service.py`:
```python
"""Conversations with agents: sending messages and recording the timeline."""

import asyncio
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Any

from a2a.types import CancelTaskRequest, Message, Role
from pydantic import BaseModel
from sqlalchemy import select

from a2a_workbench.core.a2a_json import INTERRUPTED_STATES, TERMINAL_STATES, card_from_json, to_json
from a2a_workbench.core.blobs import BlobService
from a2a_workbench.core.bus import EventBus
from a2a_workbench.core.connection.client import open_client, select_interface
from a2a_workbench.core.connection.recorder import ExchangeSink, recording_scope
from a2a_workbench.core.conversations.artifacts import ArtifactAssembler
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.conversations.options import SendOptions, build_call_context, build_request
from a2a_workbench.core.conversations.parts import (
    DataPartInput, FilePartInput, TextPartInput, build_part,
)
from a2a_workbench.core.conversations.timeline import TimelineEvent, event_from_stream_response
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import DEFAULT_WORKSPACE_ID, Agent, Conversation, TimelineEventRow


class ConversationNotFoundError(LookupError):
    """Raised when a conversation id does not exist."""


class ConversationOut(BaseModel):
    id: str
    agent_id: str
    title: str
    origin: str
    context_id: str | None
    task_id: str | None
    task_state: str | None
    last_seq: int
    created_at: datetime
    updated_at: datetime


def _out(c: Conversation) -> ConversationOut:
    return ConversationOut(id=c.id, agent_id=c.agent_id, title=c.title, origin=c.origin,
                           context_id=c.context_id, task_id=c.task_id, task_state=c.task_state,
                           last_seq=c.last_seq, created_at=c.created_at, updated_at=c.updated_at)


def _event_from_row(row: TimelineEventRow) -> TimelineEvent:
    return TimelineEvent(conversation_id=row.conversation_id, seq=row.seq, kind=row.kind, ts=row.ts,  # type: ignore[arg-type]
                         task_id=row.task_id, context_id=row.context_id,
                         exchange_id=row.exchange_id, data=row.data)


class ConversationService:
    """Sends messages through the SDK and keeps an ordered, persisted timeline.

    Each emitted event gets the next per-conversation sequence number, is stored,
    and is published as ``{"type": "event", "event": ...}`` on
    ``conversation:<id>``.
    """

    def __init__(self, db: Database, bus: EventBus, sink: ExchangeSink, blobs: BlobService) -> None:
        self._db = db
        self._bus = bus
        self._sink = sink
        self._blobs = blobs
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def create(self, agent_id: str, *, title: str | None = None, origin: str = "chat") -> ConversationOut:
        """Start an empty conversation with an agent."""
        conv = Conversation(workspace_id=DEFAULT_WORKSPACE_ID, agent_id=agent_id,
                            title=title or "New conversation", origin=origin)
        async with self._db.sessions() as session:
            session.add(conv)
            await session.commit()
        return _out(conv)

    async def get(self, conversation_id: str) -> ConversationOut:
        """Return one conversation.

        Raises:
            ConversationNotFoundError: if it does not exist.
        """
        async with self._db.sessions() as session:
            conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise ConversationNotFoundError(conversation_id)
        return _out(conv)

    async def list_for_agent(self, agent_id: str) -> list[ConversationOut]:
        """Return an agent's conversations, newest first."""
        async with self._db.sessions() as session:
            rows = (await session.execute(select(Conversation).where(Conversation.agent_id == agent_id)
                                          .order_by(Conversation.updated_at.desc()))).scalars().all()
        return [_out(c) for c in rows]

    async def events(self, conversation_id: str, after_seq: int = 0) -> list[TimelineEvent]:
        """Return stored events with ``seq > after_seq`` in order."""
        async with self._db.sessions() as session:
            rows = (await session.execute(
                select(TimelineEventRow).where(TimelineEventRow.conversation_id == conversation_id,
                                               TimelineEventRow.seq > after_seq)
                .order_by(TimelineEventRow.seq))).scalars().all()
        return [_event_from_row(r) for r in rows]

    async def _emit(self, event: TimelineEvent) -> TimelineEvent:
        async with self._db.sessions() as session:
            conv = await session.get(Conversation, event.conversation_id)
            if conv is None:
                raise ConversationNotFoundError(event.conversation_id)
            conv.last_seq += 1
            event.seq = conv.last_seq
            if event.context_id and not conv.context_id:
                conv.context_id = event.context_id
            state = event.data.get("state") if event.kind in ("task", "status") else None
            if event.task_id and state:
                conv.task_id = event.task_id
                conv.task_state = state
            if event.kind == "user_message" and conv.title == "New conversation":
                text = next((p.get("text") for p in event.data["message"].get("parts", []) if p.get("text")), None)
                if text:
                    conv.title = text[:60]
            session.add(TimelineEventRow(conversation_id=event.conversation_id, seq=event.seq,
                                         kind=event.kind, ts=event.ts, task_id=event.task_id,
                                         context_id=event.context_id, exchange_id=event.exchange_id,
                                         data=event.data))
            await session.commit()
        self._bus.publish(f"conversation:{event.conversation_id}",
                          {"type": "event", "event": event.model_dump(mode="json")})
        return event

    async def _load(self, conversation_id: str) -> tuple[Conversation, Agent]:
        async with self._db.sessions() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv is None:
                raise ConversationNotFoundError(conversation_id)
            agent = await session.get(Agent, conv.agent_id)
            assert agent is not None
        return conv, agent

    async def send(
        self, conversation_id: str,
        parts: Sequence[TextPartInput | FilePartInput | DataPartInput], options: SendOptions,
    ) -> AsyncIterator[TimelineEvent]:
        """Send a user message and yield every resulting timeline event.

        The message continues the conversation's task when that task awaits input
        or auth; otherwise it starts a new task in the conversation's context.
        Failures are yielded as ``error`` events rather than raised.
        """
        async with self._locks[conversation_id]:
            conv, agent = await self._load(conversation_id)
            card = card_from_json(agent.card)
            message = Message(message_id=uuid.uuid4().hex, role=Role.ROLE_USER,
                              parts=[await build_part(p, self._blobs.lookup) for p in parts])
            context_id = options.context_id or conv.context_id
            if context_id:
                message.context_id = context_id
            task_id = options.task_id or (conv.task_id if conv.task_state in INTERRUPTED_STATES else None)
            if task_id:
                message.task_id = task_id
            yield await self._emit(TimelineEvent(
                conversation_id=conversation_id, kind="user_message", task_id=task_id,
                context_id=context_id, data={"message": to_json(message), "options": options.model_dump(mode="json")}))
            assembler = ArtifactAssembler()
            with recording_scope("send_message", agent_id=agent.id, conversation_id=conversation_id) as scope:
                try:
                    iface = select_interface(card, options.interface_url or agent.selected_interface_url)
                    async with await open_client(card, iface, self._sink, streaming=options.stream) as client:
                        async for resp in client.send_message(build_request(message, options),
                                                              context=build_call_context(options)):
                            yield await self._emit(event_from_stream_response(
                                resp, conversation_id=conversation_id, assembler=assembler,
                                exchange_id=scope.exchange_ids[-1] if scope.exchange_ids else None))
                except Exception as exc:  # every failure becomes a visible timeline event
                    yield await self._emit(TimelineEvent(
                        conversation_id=conversation_id, kind="error", task_id=task_id,
                        exchange_id=scope.exchange_ids[-1] if scope.exchange_ids else None,
                        data=classify_error(exc)))

    async def cancel(self, conversation_id: str) -> AsyncIterator[TimelineEvent]:
        """Request cancellation of the conversation's current task and yield the outcome."""
        async with self._locks[conversation_id]:
            conv, agent = await self._load(conversation_id)
            if not conv.task_id or conv.task_state in TERMINAL_STATES:
                yield await self._emit(TimelineEvent(
                    conversation_id=conversation_id, kind="error",
                    data={"category": "workbench", "message": "There is no running task to stop."}))
                return
            card = card_from_json(agent.card)
            with recording_scope("cancel_task", agent_id=agent.id, conversation_id=conversation_id) as scope:
                try:
                    iface = select_interface(card, agent.selected_interface_url)
                    async with await open_client(card, iface, self._sink, streaming=False) as client:
                        task = await client.cancel_task(CancelTaskRequest(id=conv.task_id))
                    from a2a.types import StreamResponse
                    yield await self._emit(event_from_stream_response(
                        StreamResponse(task=task), conversation_id=conversation_id,
                        assembler=ArtifactAssembler(),
                        exchange_id=scope.exchange_ids[-1] if scope.exchange_ids else None))
                except Exception as exc:
                    yield await self._emit(TimelineEvent(
                        conversation_id=conversation_id, kind="error", task_id=conv.task_id,
                        exchange_id=scope.exchange_ids[-1] if scope.exchange_ids else None,
                        data=classify_error(exc)))
```

`core/workbench.py`:
```python
"""Wiring of the core services."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from a2a_workbench.core.blobs import BlobService
from a2a_workbench.core.bus import EventBus
from a2a_workbench.core.config import Settings
from a2a_workbench.core.conversations.service import ConversationService
from a2a_workbench.core.exchanges import ExchangeStore
from a2a_workbench.core.registry.service import AgentService
from a2a_workbench.core.store.db import Database
from a2a_workbench.core.store.models import DEFAULT_WORKSPACE_ID, Workspace


class Workbench:
    """All core services sharing one settings object, database and event bus."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.resolved_database_url)
        self.bus = EventBus()
        self.exchanges = ExchangeStore(self.db, self.bus)
        self.blobs = BlobService(self.db, settings.max_blob_bytes)
        self.agents = AgentService(self.db, self.exchanges)
        self.conversations = ConversationService(self.db, self.bus, self.exchanges, self.blobs)

    async def start(self) -> None:
        """Create the state directory and schema, and the default workspace."""
        self.settings.home.mkdir(parents=True, exist_ok=True)
        await self.db.create_schema()
        async with self.db.sessions() as session:
            if await session.get(Workspace, DEFAULT_WORKSPACE_ID) is None:
                session.add(Workspace(id=DEFAULT_WORKSPACE_ID, name="Default"))
                await session.commit()

    async def close(self) -> None:
        """Release database connections."""
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
```

- [ ] **Step 4: Run** `uv run pytest tests/core -q` → PASS
- [ ] **Step 5: Commit** `feat(core): agent registry, blobs and conversation service`

---

### Task 9: HTTP API

**Files:**
- Create: `api/__init__.py`, `api/app.py`, `api/deps.py`, `api/errors.py`, `api/routes_agents.py`, `api/routes_conversations.py`, `api/routes_misc.py`
- Test: `tests/api/conftest.py`, `tests/api/test_agents_api.py`, `tests/api/test_conversations_api.py`, `tests/api/test_misc_api.py`

**Interfaces:**
- Consumes: `Workbench` and its services.
- Produces: `create_app(settings: Settings | None = None) -> FastAPI` (state `app.state.workbench`; background sends tracked in `app.state.tasks`). Routes:
  - `GET /api/health` → `{"status":"ok","version"}`
  - `POST /api/cards/preview {url}` → `CardPreview`
  - `GET /api/agents` → `[AgentOut]`; `POST /api/agents {url, card_path?}` → 201 `AgentOut`; `GET/DELETE /api/agents/{id}`; `PATCH /api/agents/{id} {selected_interface_url}`; `POST /api/agents/{id}/refresh`
  - `GET /api/agents/{id}/conversations`; `POST /api/conversations {agent_id, title?}` → 201; `GET /api/conversations/{id}` → `{conversation, events}`; `POST /api/conversations/{id}/messages {parts, options}` → 202 `{"accepted": true}`; `POST /api/conversations/{id}/cancel` → 202
  - `POST /api/blobs` (multipart `file`) → 201 `BlobOut`; `GET /api/blobs/{id}` → bytes
  - `GET /api/exchanges?conversation_id=&agent_id=&limit=` → summaries; `GET /api/exchanges/{id}` → full record
  - Errors: `{"error": {"category", "message", ...}}` with 404 (not found), 409 (exists), 413 (blob too large), 422 (card fetch failure, interface not found, validation).

- [ ] **Step 1: Failing tests**

`tests/api/conftest.py`:
```python
import pytest
from fastapi.testclient import TestClient

from a2a_workbench.api.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c
```

`tests/api/test_agents_api.py`:
```python
def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_preview_then_add_then_list(client, zoo):
    preview = client.post("/api/cards/preview", json={"url": zoo.base_url}).json()
    assert preview["card"]["name"] == "Zoo agent" and preview["signature_status"] == "verified"
    assert preview["default_interface_url"].endswith("/a2a")
    r = client.post("/api/agents", json={"url": zoo.base_url})
    assert r.status_code == 201
    agent = r.json()
    assert client.get("/api/agents").json()[0]["id"] == agent["id"]
    assert client.post("/api/agents", json={"url": zoo.base_url}).status_code == 409


def test_add_agent_unreachable_returns_422(client):
    r = client.post("/api/agents", json={"url": "http://127.0.0.1:1"})
    assert r.status_code == 422
    assert r.json()["error"]["category"] == "transport"


def test_patch_interface_and_delete(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    r = client.patch(f"/api/agents/{agent['id']}", json={"selected_interface_url": f"{zoo.base_url}/v1"})
    assert r.json()["selected_interface_url"].endswith("/v1")
    assert client.patch(f"/api/agents/{agent['id']}", json={"selected_interface_url": "x"}).status_code == 422
    assert client.delete(f"/api/agents/{agent['id']}").status_code == 204
    assert client.get(f"/api/agents/{agent['id']}").status_code == 404
```

`tests/api/test_conversations_api.py`:
```python
import time


def _wait_for(client, conv_id, predicate, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/conversations/{conv_id}").json()
        if predicate(body["events"]):
            return body
        time.sleep(0.05)
    raise AssertionError("condition not met")


def test_send_message_runs_in_background(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    conv = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    r = client.post(f"/api/conversations/{conv['id']}/messages",
                    json={"parts": [{"kind": "text", "text": "stream"}], "options": {"stream": True}})
    assert r.status_code == 202
    body = _wait_for(client, conv["id"], lambda ev: ev and ev[-1].get("data", {}).get("state") == "completed")
    assert body["conversation"]["title"] == "stream"
    ex = client.get("/api/exchanges", params={"conversation_id": conv["id"]}).json()
    assert ex[-1]["operation"] == "send_message"
    full = client.get(f"/api/exchanges/{ex[-1]['id']}").json()
    assert full["frames"] and full["request_headers"]["a2a-version"] == "1.0"


def test_cancel_endpoint(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    conv = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    client.post(f"/api/conversations/{conv['id']}/messages",
                json={"parts": [{"kind": "text", "text": "slow 30"}],
                      "options": {"stream": False, "return_immediately": True}})
    _wait_for(client, conv["id"], lambda ev: any(e["kind"] == "task" for e in ev))
    assert client.post(f"/api/conversations/{conv['id']}/cancel").status_code == 202
    _wait_for(client, conv["id"], lambda ev: ev[-1]["data"].get("state") == "canceled")


def test_invalid_part_is_422(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    conv = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    r = client.post(f"/api/conversations/{conv['id']}/messages", json={"parts": [{"kind": "file"}]})
    assert r.status_code == 422
```

`tests/api/test_misc_api.py`:
```python
def test_blob_upload_and_download(client):
    r = client.post("/api/blobs", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 201
    blob = r.json()
    assert blob["size"] == 5 and blob["filename"] == "a.txt"
    got = client.get(f"/api/blobs/{blob['id']}")
    assert got.content == b"hello" and got.headers["content-type"].startswith("text/plain")


def test_missing_exchange_404(client):
    assert client.get("/api/exchanges/nope").status_code == 404


def test_spa_fallback_serves_index_when_built(client, tmp_path):
    r = client.get("/agents/xyz")
    assert r.status_code in (200, 404)
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement**

`api/deps.py`:
```python
"""FastAPI dependencies."""

from fastapi import Request

from a2a_workbench.core.workbench import Workbench


def get_workbench(request: Request) -> Workbench:
    """Return the Workbench owned by the running application."""
    return request.app.state.workbench
```

`api/errors.py`:
```python
"""Mapping of core exceptions to HTTP responses."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from a2a_workbench.core.blobs import BlobNotFoundError, BlobTooLargeError
from a2a_workbench.core.connection.cards import CardFetchError
from a2a_workbench.core.connection.client import InterfaceNotFoundError
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.conversations.service import ConversationNotFoundError
from a2a_workbench.core.registry.service import AgentExistsError, AgentNotFoundError


def _error(status: int, payload: dict) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": payload})


def install_error_handlers(app: FastAPI) -> None:
    """Register JSON error responses for core exceptions on ``app``."""

    @app.exception_handler(CardFetchError)
    async def _card(_: Request, exc: CardFetchError) -> JSONResponse:
        payload = classify_error(exc.cause)
        payload["message"] = str(exc)
        return _error(422, payload)

    for exc_type, status in ((AgentNotFoundError, 404), (ConversationNotFoundError, 404),
                             (BlobNotFoundError, 404), (AgentExistsError, 409),
                             (BlobTooLargeError, 413), (InterfaceNotFoundError, 422)):
        def _make(code: int):
            async def handler(_: Request, exc: Exception) -> JSONResponse:
                return _error(code, {"category": "workbench", "message": str(exc) or type(exc).__name__})
            return handler
        app.add_exception_handler(exc_type, _make(status))
```

`api/routes_agents.py`:
```python
"""Agent registry endpoints."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.registry.service import AgentOut, CardPreview
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api")


class UrlIn(BaseModel):
    url: str
    card_path: str | None = None


class AgentPatch(BaseModel):
    selected_interface_url: str


@router.post("/cards/preview")
async def preview_card(body: UrlIn, wb: Workbench = Depends(get_workbench)) -> CardPreview:
    return await wb.agents.preview(body.url)


@router.get("/agents")
async def list_agents(wb: Workbench = Depends(get_workbench)) -> list[AgentOut]:
    return await wb.agents.list()


@router.post("/agents", status_code=201)
async def add_agent(body: UrlIn, wb: Workbench = Depends(get_workbench)) -> AgentOut:
    return await wb.agents.add(body.url, body.card_path)


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, wb: Workbench = Depends(get_workbench)) -> AgentOut:
    return await wb.agents.get(agent_id)


@router.patch("/agents/{agent_id}")
async def patch_agent(agent_id: str, body: AgentPatch, wb: Workbench = Depends(get_workbench)) -> AgentOut:
    return await wb.agents.set_interface(agent_id, body.selected_interface_url)


@router.post("/agents/{agent_id}/refresh")
async def refresh_agent(agent_id: str, wb: Workbench = Depends(get_workbench)) -> AgentOut:
    return await wb.agents.refresh_card(agent_id)


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, wb: Workbench = Depends(get_workbench)) -> Response:
    await wb.agents.remove(agent_id)
    return Response(status_code=204)
```

`api/routes_conversations.py`:
```python
"""Conversation endpoints; sends run as background tasks and stream over /ws."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import PartInput
from a2a_workbench.core.conversations.service import ConversationOut
from a2a_workbench.core.conversations.timeline import TimelineEvent
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api")


class ConversationIn(BaseModel):
    agent_id: str
    title: str | None = None


class MessageIn(BaseModel):
    parts: list[PartInput] = Field(min_length=1)
    options: SendOptions = Field(default_factory=SendOptions)


def _spawn(request: Request, events: AsyncIterator[Any]) -> None:
    async def drain() -> None:
        async for _ in events:
            pass

    tasks: set[asyncio.Task[None]] = request.app.state.tasks
    task = asyncio.create_task(drain())
    tasks.add(task)
    task.add_done_callback(tasks.discard)


@router.get("/agents/{agent_id}/conversations")
async def list_conversations(agent_id: str, wb: Workbench = Depends(get_workbench)) -> list[ConversationOut]:
    await wb.agents.get(agent_id)
    return await wb.conversations.list_for_agent(agent_id)


@router.post("/conversations", status_code=201)
async def create_conversation(body: ConversationIn, wb: Workbench = Depends(get_workbench)) -> ConversationOut:
    await wb.agents.get(body.agent_id)
    return await wb.conversations.create(body.agent_id, title=body.title)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, wb: Workbench = Depends(get_workbench)) -> dict[str, Any]:
    conv = await wb.conversations.get(conversation_id)
    events: list[TimelineEvent] = await wb.conversations.events(conversation_id)
    return {"conversation": conv.model_dump(mode="json"), "events": [e.model_dump(mode="json") for e in events]}


@router.post("/conversations/{conversation_id}/messages", status_code=202)
async def send_message(conversation_id: str, body: MessageIn, request: Request,
                       wb: Workbench = Depends(get_workbench)) -> dict[str, bool]:
    await wb.conversations.get(conversation_id)
    _spawn(request, wb.conversations.send(conversation_id, body.parts, body.options))
    return {"accepted": True}


@router.post("/conversations/{conversation_id}/cancel", status_code=202)
async def cancel(conversation_id: str, request: Request, wb: Workbench = Depends(get_workbench)) -> dict[str, bool]:
    await wb.conversations.get(conversation_id)
    _spawn(request, wb.conversations.cancel(conversation_id))
    return {"accepted": True}
```

`api/routes_misc.py`:
```python
"""Health, blob and exchange endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from a2a_workbench import __version__
from a2a_workbench.api.deps import get_workbench
from a2a_workbench.core.blobs import BlobNotFoundError, BlobOut
from a2a_workbench.core.workbench import Workbench

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.post("/blobs", status_code=201)
async def upload_blob(file: UploadFile, wb: Workbench = Depends(get_workbench)) -> BlobOut:
    data = await file.read(wb.blobs.max_bytes + 1)
    return await wb.blobs.put(data, file.content_type or "application/octet-stream", file.filename)


@router.get("/blobs/{blob_id}")
async def download_blob(blob_id: str, wb: Workbench = Depends(get_workbench)) -> Response:
    blob = await wb.blobs.get(blob_id)
    if blob is None:
        raise BlobNotFoundError(blob_id)
    headers = {"content-disposition": f'inline; filename="{blob.filename}"'} if blob.filename else {}
    return Response(content=blob.data, media_type=blob.media_type, headers=headers)


@router.get("/exchanges")
async def list_exchanges(conversation_id: str | None = None, agent_id: str | None = None, limit: int = 200,
                         wb: Workbench = Depends(get_workbench)) -> list[dict[str, Any]]:
    return await wb.exchanges.list(conversation_id=conversation_id, agent_id=agent_id, limit=min(limit, 1000))


@router.get("/exchanges/{exchange_id}")
async def get_exchange(exchange_id: str, wb: Workbench = Depends(get_workbench)) -> dict[str, Any]:
    record = await wb.exchanges.get(exchange_id)
    if record is None:
        raise HTTPException(404, detail="exchange not found")
    return record
```

`api/app.py`:
```python
"""FastAPI application: JSON API, WebSocket and the single-page app."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from a2a_workbench import __version__
from a2a_workbench.api import routes_agents, routes_conversations, routes_misc, ws
from a2a_workbench.api.errors import install_error_handlers
from a2a_workbench.core.config import Settings
from a2a_workbench.core.workbench import Workbench

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Return the Workbench web application bound to ``settings``."""
    workbench = Workbench(settings or Settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await workbench.start()
        try:
            yield
        finally:
            for task in list(app.state.tasks):
                task.cancel()
            await asyncio.gather(*app.state.tasks, return_exceptions=True)
            await workbench.close()

    app = FastAPI(title="A2A Workbench", version=__version__, lifespan=lifespan)
    app.state.workbench = workbench
    app.state.tasks = set()
    install_error_handlers(app)
    for module in (routes_misc, routes_agents, routes_conversations):
        app.include_router(module.router)
    app.include_router(ws.router)
    _mount_spa(app)
    return app


def _mount_spa(app: FastAPI) -> None:
    index = STATIC_DIR / "index.html"
    if (STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse | JSONResponse:
        if path.startswith(("api/", "ws")):
            return JSONResponse({"error": {"category": "workbench", "message": "not found"}}, 404)
        candidate = STATIC_DIR / path
        if path and candidate.is_file() and STATIC_DIR in candidate.resolve().parents:
            return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"error": {"category": "workbench",
                                       "message": "Web UI not built. Run scripts/build.sh."}}, 404)
```

- [ ] **Step 4: Run** `uv run pytest tests/api -q` → PASS (after Task 10 creates `api/ws.py`; create an empty router stub in this task: `router = APIRouter()`)
- [ ] **Step 5: Commit** `feat(api): REST endpoints for agents, conversations, blobs and exchanges`

---

### Task 10: WebSocket hub with replay

**Files:**
- Create/replace: `api/ws.py`
- Test: `tests/api/test_ws.py`

**Interfaces:**
- Protocol (client → server): `{"op":"subscribe","topic":"conversation:<id>","after_seq":<int>}`, `{"op":"subscribe","topic":"exchanges:<id>"}`, `{"op":"unsubscribe","topic":...}`. Server → client: `{"topic":..., "type":"event","event":{...}}` or `{"topic":..., "type":"exchange","exchange":{...}}`; `{"type":"error","message":...}` for bad ops.
- Guarantee: for `conversation:` topics, events with `seq > after_seq` are delivered exactly once, in order, across replay and live.

- [ ] **Step 1: Failing test** `tests/api/test_ws.py`

```python
def test_ws_replays_after_seq_without_duplicates(client, zoo):
    agent = client.post("/api/agents", json={"url": zoo.base_url}).json()
    conv = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    topic = f"conversation:{conv['id']}"
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "subscribe", "topic": topic, "after_seq": 0})
        client.post(f"/api/conversations/{conv['id']}/messages", json={"parts": [{"kind": "text", "text": "stream"}]})
        seen = []
        while not seen or seen[-1]["data"].get("state") != "completed":
            msg = ws.receive_json()
            assert msg["topic"] == topic
            seen.append(msg["event"])
    assert [e["seq"] for e in seen] == list(range(1, len(seen) + 1))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "subscribe", "topic": topic, "after_seq": 3})
        replay = [ws.receive_json()["event"]["seq"] for _ in range(len(seen) - 3)]
    assert replay == list(range(4, len(seen) + 1))


def test_ws_rejects_unknown_op(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"op": "dance"})
        assert ws.receive_json()["type"] == "error"
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement** `api/ws.py`

```python
"""Multiplexed WebSocket delivering conversation events and exchange summaries."""

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from a2a_workbench.core.workbench import Workbench

router = APIRouter()


async def _pump(ws: WebSocket, wb: Workbench, topic: str, after_seq: int) -> None:
    async with wb.bus.subscription(topic) as queue:
        last = after_seq
        if topic.startswith("conversation:"):
            for event in await wb.conversations.events(topic.split(":", 1)[1], after_seq):
                await ws.send_json({"topic": topic, "type": "event", "event": event.model_dump(mode="json")})
                last = event.seq
        while True:
            payload: dict[str, Any] = await queue.get()
            if payload.get("type") == "event":
                if payload["event"]["seq"] <= last:
                    continue
                last = payload["event"]["seq"]
            await ws.send_json({"topic": topic, **payload})


@router.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    """Serve subscribe/unsubscribe requests until the client disconnects."""
    await ws.accept()
    wb: Workbench = ws.app.state.workbench
    pumps: dict[str, asyncio.Task[None]] = {}
    try:
        while True:
            msg = await ws.receive_json()
            op, topic = msg.get("op"), msg.get("topic")
            if op == "subscribe" and isinstance(topic, str) and topic.startswith(("conversation:", "exchanges:")):
                if topic in pumps:
                    pumps.pop(topic).cancel()
                pumps[topic] = asyncio.create_task(_pump(ws, wb, topic, int(msg.get("after_seq") or 0)))
            elif op == "unsubscribe" and topic in pumps:
                pumps.pop(topic).cancel()
            else:
                await ws.send_json({"type": "error", "message": f"unsupported message: {msg}"})
    except WebSocketDisconnect:
        pass
    finally:
        for task in pumps.values():
            task.cancel()
        for task in pumps.values():
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
```

- [ ] **Step 4: Run** `uv run pytest tests/api -q` → PASS
- [ ] **Step 5: Commit** `feat(api): websocket hub with sequence-based replay`

---

### Task 11: CLI — serve, agents, card, send, fixtures

**Files:**
- Create: `cli/__init__.py`, `cli/output.py`, `cli/main.py`
- Test: `tests/cli/test_cli.py`

**Interfaces:**
- Produces: Typer `app`; `ExitCode(IntEnum)`: `OK=0, CHECKS_FAILED=1, USAGE=2, CONNECTION=3, AUTH=4, PROTOCOL=5, INTERNAL=6`; `exit_code_for(category) -> ExitCode`.
- Commands: `serve [--host] [--port] [--open/--no-open]`; `agents add <url> [--card-path] [--json]`; `agents list [--json]`; `agents remove <ref>`; `card <url-or-agent> [--json]`; `send <agent-or-url> <text> [--file PATH]... [--url URL]... [--data JSON] [--stream/--no-stream] [--return-immediately] [--accept MODE]... [--history-length N] [--extension URI]... [--metadata JSON] [--context-id ID] [--task-id ID] [--interface URL] [--json]`; `fixtures [--host] [--port] [--unsigned]`.

- [ ] **Step 1: Failing tests** `tests/cli/test_cli.py`

```python
import json

from typer.testing import CliRunner

from a2a_workbench.cli.main import app

runner = CliRunner()


def test_card_json(zoo):
    r = runner.invoke(app, ["card", zoo.base_url, "--json"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["card"]["name"] == "Zoo agent" and out["signature_status"] == "verified"


def test_card_unreachable_exit_code_3():
    r = runner.invoke(app, ["card", "http://127.0.0.1:1", "--json"])
    assert r.exit_code == 3
    assert json.loads(r.stdout)["error"]["category"] == "transport"


def test_agents_add_list_remove(zoo):
    assert runner.invoke(app, ["agents", "add", zoo.base_url, "--json"]).exit_code == 0
    listed = json.loads(runner.invoke(app, ["agents", "list", "--json"]).stdout)
    assert listed[0]["name"] == "Zoo agent"
    assert runner.invoke(app, ["agents", "remove", "Zoo agent"]).exit_code == 0
    assert json.loads(runner.invoke(app, ["agents", "list", "--json"]).stdout) == []


def test_send_ndjson_stream(zoo):
    r = runner.invoke(app, ["send", zoo.base_url, "stream", "--json"])
    assert r.exit_code == 0, r.output
    events = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    assert events[0]["kind"] == "user_message"
    assert events[-1]["data"]["state"] == "completed"


def test_send_with_options_reaches_agent(zoo):
    r = runner.invoke(app, ["send", zoo.base_url, "inspect", "--json", "--accept", "text/plain",
                            "--history-length", "1", "--extension", "https://e/x", "--metadata", '{"a":1}',
                            "--data", '{"n":2}'])
    events = [json.loads(line) for line in r.stdout.splitlines()]
    report = next(e for e in events if e["kind"] == "artifact")["data"]["assembled"]["parts"][0]["data"]
    assert report["requestedExtensions"] == ["https://e/x"]
    assert report["message"]["parts"][1]["data"] == {"n": 2}


def test_send_human_output(zoo):
    r = runner.invoke(app, ["send", zoo.base_url, "echo hello"])
    assert r.exit_code == 0 and "hello" in r.stdout and "completed" in r.stdout.lower()


def test_bad_metadata_json_is_usage_error(zoo):
    assert runner.invoke(app, ["send", zoo.base_url, "x", "--metadata", "{bad"]).exit_code == 2
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Implement**

`cli/output.py`:
```python
"""Exit codes and printers for the CLI."""

import json
import sys
from enum import IntEnum
from typing import Any

from a2a_workbench.core.conversations.timeline import TimelineEvent


class ExitCode(IntEnum):
    OK = 0
    CHECKS_FAILED = 1
    USAGE = 2
    CONNECTION = 3
    AUTH = 4
    PROTOCOL = 5
    INTERNAL = 6


_CATEGORY_EXIT = {"transport": ExitCode.CONNECTION, "auth": ExitCode.AUTH,
                  "protocol": ExitCode.PROTOCOL, "workbench": ExitCode.INTERNAL}


def exit_code_for(category: str) -> ExitCode:
    """Return the exit code for an error category."""
    return _CATEGORY_EXIT.get(category, ExitCode.INTERNAL)


def print_json(value: Any) -> None:
    """Write ``value`` as one JSON document to stdout."""
    sys.stdout.write(json.dumps(value, default=str) + "\n")
    sys.stdout.flush()


def _texts(parts: list[dict[str, Any]]) -> str:
    out = []
    for p in parts:
        if "text" in p:
            out.append(p["text"])
        elif "data" in p:
            out.append(json.dumps(p["data"]))
        elif "url" in p:
            out.append(f"[file {p.get('filename') or ''} {p['url']}]")
        elif "raw" in p:
            out.append(f"[file {p.get('filename') or ''} {p.get('mediaType') or ''}]")
    return "".join(out)


def describe_event(event: TimelineEvent) -> str | None:
    """Return a one-line human description of a timeline event, or None to skip it."""
    d = event.data
    if event.kind == "user_message":
        return f"you: {_texts(d['message'].get('parts', []))}"
    if event.kind == "message":
        return f"agent: {_texts(d['message'].get('parts', []))}"
    if event.kind == "task":
        return f"task {event.task_id}: {d['state']}"
    if event.kind == "status":
        message = d.get("status", {}).get("message")
        suffix = f" — {_texts(message.get('parts', []))}" if message else ""
        return f"status: {d['state']}{suffix}"
    if event.kind == "artifact":
        if not d["last_chunk"] and d["append"]:
            return None
        art = d["assembled"]
        return f"artifact {art.get('name') or art.get('artifactId')}: {_texts(art.get('parts', []))}"
    if event.kind == "error":
        return f"error ({d['category']}): {d['message']}"
    return None
```

`cli/main.py`:
```python
"""`a2a-workbench` command-line interface."""

import asyncio
import json
import mimetypes
import sys
import webbrowser
from pathlib import Path
from typing import Annotated, Any

import typer

from a2a_workbench.cli.output import ExitCode, describe_event, exit_code_for, print_json
from a2a_workbench.core.config import Settings
from a2a_workbench.core.connection.cards import CardFetchError
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import DataPartInput, FilePartInput, TextPartInput
from a2a_workbench.core.registry.service import AgentNotFoundError
from a2a_workbench.core.workbench import Workbench

app = typer.Typer(no_args_is_help=True, help="Debug, test and conformance-check A2A agents.")
agents_app = typer.Typer(no_args_is_help=True, help="Manage registered agents.")
app.add_typer(agents_app, name="agents")

JsonFlag = Annotated[bool, typer.Option("--json", help="Machine-readable JSON output.")]


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _fail(category: str, message: str, as_json: bool) -> None:
    if as_json:
        print_json({"error": {"category": category, "message": message}})
    else:
        typer.echo(f"error ({category}): {message}", err=True)
    raise typer.Exit(exit_code_for(category))


def _parse_json(value: str | None, option: str) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        typer.echo(f"{option} is not valid JSON: {exc}", err=True)
        raise typer.Exit(ExitCode.USAGE) from exc


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Interface to bind.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to listen on.")] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open", help="Open the UI in a browser.")] = False,
) -> None:
    """Run the web UI and API."""
    import uvicorn

    from a2a_workbench.api.app import create_app

    settings = Settings()
    bind_host, bind_port = host or settings.host, port or settings.port
    if open_browser:
        webbrowser.open(f"http://{bind_host}:{bind_port}")
    uvicorn.run(create_app(settings), host=bind_host, port=bind_port, log_level="info")


@agents_app.command("add")
def agents_add(url: str, card_path: Annotated[str | None, typer.Option()] = None, as_json: JsonFlag = False) -> None:
    """Register the agent at URL."""
    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            try:
                agent = await wb.agents.add(url, card_path)
            except CardFetchError as exc:
                _fail(classify_error(exc.cause)["category"], str(exc), as_json)
            except ValueError as exc:
                _fail("workbench", str(exc), as_json)
            if as_json:
                print_json(agent.model_dump(mode="json"))
            else:
                typer.echo(f"Registered {agent.name} ({agent.id}) via {agent.selected_interface_url}")
    _run(go())


@agents_app.command("list")
def agents_list(as_json: JsonFlag = False) -> None:
    """List registered agents."""
    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            agents = await wb.agents.list()
            if as_json:
                print_json([a.model_dump(mode="json") for a in agents])
            else:
                for a in agents:
                    typer.echo(f"{a.id}  {a.name}  {a.base_url}  [{a.signature_status}]")
    _run(go())


@agents_app.command("remove")
def agents_remove(ref: str) -> None:
    """Remove an agent by id, name or URL."""
    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            try:
                agent = await wb.agents.resolve(ref)
            except AgentNotFoundError:
                _fail("workbench", f"No agent matches {ref}", False)
            await wb.agents.remove(agent.id)
            typer.echo(f"Removed {agent.name}")
    _run(go())


@app.command()
def card(target: str, as_json: JsonFlag = False) -> None:
    """Fetch and verify an agent card (TARGET is a URL or a registered agent)."""
    async def go() -> None:
        async with Workbench.open(Settings()) as wb:
            url = target
            try:
                url = (await wb.agents.resolve(target)).base_url
            except AgentNotFoundError:
                pass
            try:
                preview = await wb.agents.preview(url)
            except CardFetchError as exc:
                _fail(classify_error(exc.cause)["category"], str(exc), as_json)
            if as_json:
                print_json(preview.model_dump(mode="json"))
                return
            c = preview.card
            typer.echo(f"{c.get('name')} {c.get('version', '')} — {c.get('description', '')}")
            typer.echo(f"signature: {preview.signature_status}")
            for i in preview.interfaces:
                typer.echo(f"  {i.binding:<10} {i.protocol_version:<5} {i.url}")
            for s in c.get("skills", []):
                typer.echo(f"  skill {s.get('id')}: {s.get('name')} — {s.get('description', '')}")
    _run(go())


@app.command()
def send(
    target: Annotated[str, typer.Argument(help="Registered agent (id, name, URL) or an agent URL.")],
    text: Annotated[str, typer.Argument(help="Message text.")],
    file: Annotated[list[Path], typer.Option("--file", help="Attach a file as raw bytes.")] = [],  # noqa: B006
    url: Annotated[list[str], typer.Option("--url", help="Attach a file by URL.")] = [],  # noqa: B006
    data: Annotated[str | None, typer.Option(help="Attach a JSON data part.")] = None,
    stream: Annotated[bool, typer.Option("--stream/--no-stream")] = True,
    return_immediately: Annotated[bool, typer.Option("--return-immediately")] = False,
    accept: Annotated[list[str], typer.Option("--accept", help="Accepted output media type.")] = [],  # noqa: B006
    history_length: Annotated[int | None, typer.Option(min=0)] = None,
    extension: Annotated[list[str], typer.Option("--extension", help="Activate an extension URI.")] = [],  # noqa: B006
    metadata: Annotated[str | None, typer.Option(help="Message metadata as JSON.")] = None,
    context_id: Annotated[str | None, typer.Option()] = None,
    task_id: Annotated[str | None, typer.Option()] = None,
    interface: Annotated[str | None, typer.Option(help="Interface URL to use.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Send a message and print every event (NDJSON with --json)."""
    meta = _parse_json(metadata, "--metadata")
    data_value = _parse_json(data, "--data")
    parts: list[TextPartInput | FilePartInput | DataPartInput] = [TextPartInput(text=text)]
    for path in file:
        import base64
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(FilePartInput(raw_base64=base64.b64encode(path.read_bytes()).decode(),
                                   media_type=media_type, filename=path.name))
    parts.extend(FilePartInput(url=u) for u in url)
    if data is not None:
        parts.append(DataPartInput(data=data_value))
    options = SendOptions(stream=stream, return_immediately=return_immediately, accepted_output_modes=accept,
                          history_length=history_length, extensions=extension, message_metadata=meta,
                          context_id=context_id, task_id=task_id, interface_url=interface)

    async def go() -> int:
        async with Workbench.open(Settings()) as wb:
            try:
                agent = await wb.agents.resolve(target)
            except AgentNotFoundError:
                try:
                    agent = await wb.agents.add(target)
                except CardFetchError as exc:
                    _fail(classify_error(exc.cause)["category"], str(exc), as_json)
                if not as_json:
                    typer.echo(f"Registered {agent.name}", err=True)
            conv = await wb.conversations.create(agent.id, origin="cli")
            code = ExitCode.OK
            async for event in wb.conversations.send(conv.id, parts, options):
                if as_json:
                    print_json(event.model_dump(mode="json"))
                elif (line := describe_event(event)) is not None:
                    typer.echo(line)
                if event.kind == "error":
                    code = exit_code_for(event.data["category"])
            return int(code)

    code = _run(go())
    if code:
        raise typer.Exit(code)


@app.command()
def fixtures(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 9999,
    unsigned: Annotated[bool, typer.Option("--unsigned", help="Serve an unsigned card.")] = False,
) -> None:
    """Run the zoo reference agent until interrupted."""
    import uvicorn

    from a2a_workbench.fixtures.zoo import build_zoo_app

    base_url = f"http://{host}:{port}"
    typer.echo(f"Zoo agent at {base_url}", err=True)
    uvicorn.run(build_zoo_app(base_url, signed=not unsigned), host=host, port=port, log_level="info")


def main() -> None:
    """Entry point that maps unexpected exceptions to exit code 6."""
    try:
        app()
    except Exception as exc:  # pragma: no cover
        typer.echo(f"internal error: {exc}", err=True)
        sys.exit(ExitCode.INTERNAL)
```

- [ ] **Step 4: Run** `uv run pytest tests/cli -q` → PASS
- [ ] **Step 5: Commit** `feat(cli): serve, agents, card, send and fixtures commands`

---

### Task 12: Web app scaffold, design tokens, API/WS clients, timeline model

**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/index.html`, `web/src/main.tsx`, `web/src/styles.css`, `web/src/lib/{types,api,ws,labels,timeline,parts}.ts`, `web/src/test/setup.ts`
- Test: `web/src/lib/labels.test.ts`, `web/src/lib/timeline.test.ts`, `web/src/lib/ws.test.ts`

**Interfaces:**
- Produces (TypeScript):
  - `types.ts`: `Agent`, `InterfaceInfo`, `CardPreview`, `Conversation`, `TimelineEvent`, `ExchangeSummary`, `ExchangeRecord`, `PartInput`, `SendOptions`, `A2APart` (camelCase JSON as sent by the server).
  - `api.ts`: `api.listAgents()`, `api.previewCard(url)`, `api.addAgent(url)`, `api.deleteAgent(id)`, `api.patchAgent(id, url)`, `api.refreshAgent(id)`, `api.listConversations(agentId)`, `api.createConversation(agentId)`, `api.getConversation(id)`, `api.sendMessage(id, parts, options)`, `api.cancel(id)`, `api.uploadBlob(file)`, `api.listExchanges(conversationId)`, `api.getExchange(id)`; `ApiError` with `.category`.
  - `ws.ts`: `class Hub` with `subscribe(topic, afterSeq, onMessage) => unsubscribe`; reconnects with backoff and re-subscribes using the highest `seq` seen.
  - `labels.ts`: `stateLabel(state)` → `{label, tone}` with tone in `ok|warn|bad|run|off|auth`; `bindingLabel(binding)`.
  - `timeline.ts`: `buildTurns(events) => Turn[]`, where `Turn = {kind:'user', event} | {kind:'agent', taskId, contextId, states: string[], current: string|null, artifacts: Record<string, A2AArtifact>, messages: A2AMessage[], statusMessage: A2AMessage|null, events: TimelineEvent[], error: ErrorData|null}`.
  - `parts.ts`: `partKind(p)`, `joinText(parts)`, `dataUrl(p)`.

- [ ] **Step 1: Scaffold.** `web/package.json`:

```json
{
  "name": "a2a-workbench-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "test:watch": "vitest",
    "e2e": "playwright test",
    "lint": "tsc -b --noEmit"
  },
  "dependencies": {
    "@radix-ui/react-popover": "^1.1.0",
    "@radix-ui/react-dialog": "^1.1.0",
    "@radix-ui/react-switch": "^1.1.0",
    "@tanstack/react-query": "^5.60.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-markdown": "^10.0.0",
    "react-router": "^7.0.0",
    "remark-gfm": "^4.0.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.50.0",
    "@tailwindcss/vite": "^4.0.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^5.0.0",
    "jsdom": "^26.0.0",
    "tailwindcss": "^4.0.0",
    "typescript": "~5.8.0",
    "vite": "^7.0.0",
    "vitest": "^3.0.0"
  }
}
```
(Pin exact resolved versions with `pnpm install`; if a newer major breaks, keep the range above.)

`web/vite.config.ts`:
```ts
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8484", "/ws": { target: "ws://127.0.0.1:8484", ws: true } },
  },
  build: { outDir: "dist", emptyOutDir: true },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
});
```

`web/src/styles.css`: the CSS variables from `docs/design/ui-mockup.html` (`:root` light, `[data-theme=dark]` dark) under `@import "tailwindcss";` with `@theme` mapping `--color-bg`, `--color-surface`, `--color-soft`, `--color-line`, `--color-text`, `--color-muted`, `--color-dim`, `--color-brand`, `--color-brand-soft`, `--color-green`, `--color-amber`, `--color-red`, `--color-blue` (and `-soft` variants), fonts Inter / JetBrains Mono. Component classes from the mockup (`.btn`, `.btn.primary`, `.tab`, `.state`, `.s-ok` …, `.cbox`, `.drawer`, `.code`, `.note`) are ported verbatim as plain CSS below the import, so the components match the approved design.

- [ ] **Step 2: Failing tests**

`web/src/lib/labels.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { stateLabel } from "./labels";

describe("stateLabel", () => {
  it("maps every A2A task state to plain language", () => {
    expect(stateLabel("submitted").label).toBe("Received");
    expect(stateLabel("working")).toEqual({ label: "Working", tone: "run", protocol: "working" });
    expect(stateLabel("input_required").label).toBe("Needs your input");
    expect(stateLabel("auth_required").label).toBe("Needs sign-in");
    expect(stateLabel("completed").tone).toBe("ok");
    expect(stateLabel("failed").tone).toBe("bad");
    expect(stateLabel("canceled").label).toBe("Stopped");
    expect(stateLabel("rejected").label).toBe("Declined");
    expect(stateLabel("weird").label).toBe("weird");
  });
});
```

`web/src/lib/timeline.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { buildTurns } from "./timeline";
import type { TimelineEvent } from "./types";

const ev = (seq: number, kind: TimelineEvent["kind"], data: Record<string, unknown>, task_id: string | null = "t1"): TimelineEvent =>
  ({ conversation_id: "c", seq, kind, ts: "2026-10-07T00:00:00Z", task_id, context_id: "x", exchange_id: "e", data });

describe("buildTurns", () => {
  it("groups agent events after each user message into one turn", () => {
    const turns = buildTurns([
      ev(1, "user_message", { message: { parts: [{ text: "hi" }] } }, null),
      ev(2, "task", { state: "submitted", task: { id: "t1" } }),
      ev(3, "status", { state: "working", status: {} }),
      ev(4, "artifact", { append: false, last_chunk: true, artifact: {}, assembled: { artifactId: "a", parts: [{ text: "x" }] } }),
      ev(5, "status", { state: "completed", status: {} }),
    ]);
    expect(turns.map((t) => t.kind)).toEqual(["user", "agent"]);
    const agent = turns[1];
    if (agent.kind !== "agent") throw new Error();
    expect(agent.states).toEqual(["submitted", "working", "completed"]);
    expect(agent.current).toBe("completed");
    expect(agent.artifacts.a.parts).toEqual([{ text: "x" }]);
  });

  it("keeps only the latest assembled version of each artifact", () => {
    const turns = buildTurns([
      ev(1, "user_message", { message: { parts: [] } }, null),
      ev(2, "artifact", { append: false, last_chunk: false, assembled: { artifactId: "a", parts: [{ text: "1" }] } }),
      ev(3, "artifact", { append: true, last_chunk: true, assembled: { artifactId: "a", parts: [{ text: "1" }, { text: "2" }] } }),
    ]);
    const agent = turns[1];
    if (agent.kind !== "agent") throw new Error();
    expect(agent.artifacts.a.parts).toHaveLength(2);
  });

  it("captures the status message of an interrupted task and errors", () => {
    const turns = buildTurns([
      ev(1, "user_message", { message: { parts: [] } }, null),
      ev(2, "status", { state: "input_required", status: { message: { parts: [{ text: "A or B?" }] } } }),
      ev(3, "error", { category: "transport", message: "down" }),
    ]);
    const agent = turns[1];
    if (agent.kind !== "agent") throw new Error();
    expect(agent.statusMessage?.parts[0]).toEqual({ text: "A or B?" });
    expect(agent.error?.category).toBe("transport");
  });

  it("collects direct agent messages", () => {
    const turns = buildTurns([
      ev(1, "user_message", { message: { parts: [] } }, null),
      ev(2, "message", { message: { role: "ROLE_AGENT", parts: [{ text: "yo" }] } }, null),
    ]);
    const agent = turns[1];
    if (agent.kind !== "agent") throw new Error();
    expect(agent.messages[0].parts[0]).toEqual({ text: "yo" });
  });
});
```

`web/src/lib/ws.test.ts`:
```ts
import { describe, expect, it, vi } from "vitest";
import { Hub } from "./ws";

class FakeSocket {
  static instances: FakeSocket[] = [];
  sent: string[] = [];
  onopen?: () => void; onmessage?: (e: { data: string }) => void; onclose?: () => void;
  readyState = 0;
  constructor(public url: string) { FakeSocket.instances.push(this); }
  send(d: string) { this.sent.push(d); }
  close() { this.onclose?.(); }
  open() { this.readyState = 1; this.onopen?.(); }
}

describe("Hub", () => {
  it("re-subscribes after reconnect from the last seen seq", async () => {
    vi.useFakeTimers();
    const hub = new Hub("ws://x/ws", FakeSocket as unknown as typeof WebSocket);
    const got: number[] = [];
    hub.subscribe("conversation:c", 0, (m) => got.push((m.event as { seq: number }).seq));
    const s1 = FakeSocket.instances[0];
    s1.open();
    expect(JSON.parse(s1.sent[0])).toEqual({ op: "subscribe", topic: "conversation:c", after_seq: 0 });
    s1.onmessage?.({ data: JSON.stringify({ topic: "conversation:c", type: "event", event: { seq: 4 } }) });
    s1.close();
    await vi.advanceTimersByTimeAsync(1000);
    const s2 = FakeSocket.instances[1];
    s2.open();
    expect(JSON.parse(s2.sent[0]).after_seq).toBe(4);
    expect(got).toEqual([4]);
    vi.useRealTimers();
  });
});
```

- [ ] **Step 3: Implement**

`web/src/lib/labels.ts`:
```ts
export type Tone = "ok" | "warn" | "bad" | "run" | "off" | "auth";

const STATES: Record<string, { label: string; tone: Tone }> = {
  submitted: { label: "Received", tone: "run" },
  working: { label: "Working", tone: "run" },
  input_required: { label: "Needs your input", tone: "warn" },
  auth_required: { label: "Needs sign-in", tone: "auth" },
  completed: { label: "Done", tone: "ok" },
  failed: { label: "Failed", tone: "bad" },
  canceled: { label: "Stopped", tone: "off" },
  rejected: { label: "Declined", tone: "bad" },
  unspecified: { label: "Unknown", tone: "off" },
};

/** Plain-language label and tone for an A2A task state, keeping the protocol name. */
export function stateLabel(state: string): { label: string; tone: Tone; protocol: string } {
  const known = STATES[state];
  return { label: known?.label ?? state, tone: known?.tone ?? "off", protocol: state };
}

const BINDINGS: Record<string, string> = { JSONRPC: "JSON-RPC", "HTTP+JSON": "REST", GRPC: "gRPC" };

/** Display name of a protocol binding. */
export function bindingLabel(binding: string): string {
  return BINDINGS[binding] ?? binding;
}

export const TERMINAL = new Set(["completed", "failed", "canceled", "rejected"]);
export const INTERRUPTED = new Set(["input_required", "auth_required"]);
```

`web/src/lib/types.ts`:
```ts
export type A2APart = {
  text?: string; raw?: string; url?: string; data?: unknown;
  mediaType?: string; filename?: string; metadata?: Record<string, unknown>;
};
export type A2AMessage = { messageId?: string; role?: string; parts: A2APart[]; contextId?: string; taskId?: string; metadata?: Record<string, unknown> };
export type A2AArtifact = { artifactId: string; name?: string; description?: string; parts: A2APart[]; metadata?: Record<string, unknown> };
export type InterfaceInfo = { url: string; binding: string; protocol_version: string; tenant: string; supported: boolean };
export type AgentCardJson = Record<string, any>;
export type Agent = {
  id: string; name: string; base_url: string; card_path: string | null; card: AgentCardJson;
  signature_status: "verified" | "invalid" | "unsigned" | "unverifiable"; signature_detail: string | null;
  selected_interface_url: string | null; interfaces: InterfaceInfo[]; created_at: string; updated_at: string;
};
export type CardPreview = {
  card: AgentCardJson; signature_status: Agent["signature_status"]; signature_detail: string | null;
  interfaces: InterfaceInfo[]; default_interface_url: string | null; exchange_ids: string[];
};
export type Conversation = {
  id: string; agent_id: string; title: string; origin: string; context_id: string | null;
  task_id: string | null; task_state: string | null; last_seq: number; created_at: string; updated_at: string;
};
export type ErrorData = { category: "transport" | "protocol" | "auth" | "workbench"; message: string; code?: number; reason?: string; http_status?: number; data?: unknown };
export type TimelineEvent = {
  conversation_id: string; seq: number; kind: "user_message" | "message" | "task" | "status" | "artifact" | "error";
  ts: string; task_id: string | null; context_id: string | null; exchange_id: string | null; data: Record<string, any>;
};
export type ExchangeSummary = {
  id: string; operation: string; http_method: string; url: string; started_at: string; status: number | null;
  duration_ms: number | null; error: string | null; frame_count: number;
};
export type ExchangeRecord = ExchangeSummary & {
  request_headers: Record<string, string>; request_body: string | null; response_headers: Record<string, string>;
  response_body: string | null; frames: { t_ms: number; data: string }[]; truncated: boolean;
};
export type PartInput =
  | { kind: "text"; text: string }
  | { kind: "file"; blob_id?: string; url?: string; media_type?: string; filename?: string }
  | { kind: "data"; data: unknown };
export type SendOptions = {
  stream: boolean; return_immediately: boolean; accepted_output_modes: string[]; history_length: number | null;
  extensions: string[]; message_metadata: Record<string, unknown> | null; reference_task_ids: string[];
};
export const DEFAULT_OPTIONS: SendOptions = {
  stream: true, return_immediately: false, accepted_output_modes: [], history_length: null,
  extensions: [], message_metadata: null, reference_task_ids: [],
};
```

`web/src/lib/api.ts`:
```ts
import type { Agent, CardPreview, Conversation, ExchangeRecord, ExchangeSummary, PartInput, SendOptions, TimelineEvent } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public category: string, message: string) { super(message); }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = init.body instanceof FormData ? undefined : { "content-type": "application/json" };
  const res = await fetch(path, { ...init, headers: { ...headers, ...init.headers } });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = body.error ?? { category: "workbench", message: body.detail ?? res.statusText };
    const message = typeof err.message === "string" ? err.message : JSON.stringify(body.detail ?? err);
    throw new ApiError(res.status, err.category ?? "workbench", message);
  }
  return body as T;
}

const json = (b: unknown) => JSON.stringify(b);

export const api = {
  listAgents: () => call<Agent[]>("/api/agents"),
  previewCard: (url: string) => call<CardPreview>("/api/cards/preview", { method: "POST", body: json({ url }) }),
  addAgent: (url: string) => call<Agent>("/api/agents", { method: "POST", body: json({ url }) }),
  deleteAgent: (id: string) => call<void>(`/api/agents/${id}`, { method: "DELETE" }),
  patchAgent: (id: string, selected_interface_url: string) =>
    call<Agent>(`/api/agents/${id}`, { method: "PATCH", body: json({ selected_interface_url }) }),
  refreshAgent: (id: string) => call<Agent>(`/api/agents/${id}/refresh`, { method: "POST" }),
  listConversations: (agentId: string) => call<Conversation[]>(`/api/agents/${agentId}/conversations`),
  createConversation: (agent_id: string) => call<Conversation>("/api/conversations", { method: "POST", body: json({ agent_id }) }),
  getConversation: (id: string) => call<{ conversation: Conversation; events: TimelineEvent[] }>(`/api/conversations/${id}`),
  sendMessage: (id: string, parts: PartInput[], options: SendOptions) =>
    call<{ accepted: boolean }>(`/api/conversations/${id}/messages`, { method: "POST", body: json({ parts, options }) }),
  cancel: (id: string) => call<{ accepted: boolean }>(`/api/conversations/${id}/cancel`, { method: "POST" }),
  uploadBlob: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<{ id: string; media_type: string; filename: string | null; size: number }>("/api/blobs", { method: "POST", body: form });
  },
  listExchanges: (conversationId: string) => call<ExchangeSummary[]>(`/api/exchanges?conversation_id=${conversationId}`),
  getExchange: (id: string) => call<ExchangeRecord>(`/api/exchanges/${id}`),
};
```

`web/src/lib/ws.ts`:
```ts
type Message = { topic: string; type: string; [k: string]: unknown };
type Sub = { topic: string; lastSeq: number; handlers: Set<(m: Message) => void> };

/** WebSocket client that multiplexes topic subscriptions and resumes after reconnects. */
export class Hub {
  private socket: WebSocket | null = null;
  private subs = new Map<string, Sub>();
  private retry = 0;

  constructor(private url: string, private Socket: typeof WebSocket = WebSocket) {}

  subscribe(topic: string, afterSeq: number, handler: (m: Message) => void): () => void {
    let sub = this.subs.get(topic);
    if (!sub) {
      sub = { topic, lastSeq: afterSeq, handlers: new Set() };
      this.subs.set(topic, sub);
      this.sendSubscribe(sub);
    }
    sub.handlers.add(handler);
    this.ensure();
    return () => {
      sub!.handlers.delete(handler);
      if (sub!.handlers.size === 0) {
        this.subs.delete(topic);
        this.send({ op: "unsubscribe", topic });
      }
    };
  }

  private ensure() {
    if (this.socket) return;
    const socket = new this.Socket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      this.retry = 0;
      for (const sub of this.subs.values()) this.sendSubscribe(sub);
    };
    socket.onmessage = (e) => {
      const msg = JSON.parse(String(e.data)) as Message;
      const sub = this.subs.get(msg.topic);
      if (!sub) return;
      const seq = (msg.event as { seq?: number } | undefined)?.seq;
      if (typeof seq === "number") sub.lastSeq = Math.max(sub.lastSeq, seq);
      sub.handlers.forEach((h) => h(msg));
    };
    socket.onclose = () => {
      this.socket = null;
      if (this.subs.size === 0) return;
      const delay = Math.min(1000 * 2 ** this.retry++, 10000);
      setTimeout(() => this.ensure(), delay);
    };
  }

  private sendSubscribe(sub: Sub) {
    this.send({ op: "subscribe", topic: sub.topic, after_seq: sub.lastSeq });
  }

  private send(payload: unknown) {
    if (this.socket && this.socket.readyState === 1) this.socket.send(JSON.stringify(payload));
  }
}

const scheme = typeof location !== "undefined" && location.protocol === "https:" ? "wss" : "ws";
export const hub = typeof location !== "undefined" ? new Hub(`${scheme}://${location.host}/ws`) : (null as unknown as Hub);
```

`web/src/lib/timeline.ts`:
```ts
import type { A2AArtifact, A2AMessage, ErrorData, TimelineEvent } from "./types";

export type UserTurn = { kind: "user"; event: TimelineEvent };
export type AgentTurn = {
  kind: "agent"; taskId: string | null; contextId: string | null; states: string[]; current: string | null;
  artifacts: Record<string, A2AArtifact>; messages: A2AMessage[]; statusMessage: A2AMessage | null;
  events: TimelineEvent[]; error: ErrorData | null;
};
export type Turn = UserTurn | AgentTurn;

const emptyAgent = (): AgentTurn => ({
  kind: "agent", taskId: null, contextId: null, states: [], current: null, artifacts: {}, messages: [],
  statusMessage: null, events: [], error: null,
});

/** Group a conversation's events into alternating user and agent turns. */
export function buildTurns(events: TimelineEvent[]): Turn[] {
  const turns: Turn[] = [];
  let agent: AgentTurn | null = null;
  for (const e of [...events].sort((a, b) => a.seq - b.seq)) {
    if (e.kind === "user_message") {
      turns.push({ kind: "user", event: e });
      agent = null;
      continue;
    }
    if (!agent) {
      agent = emptyAgent();
      turns.push(agent);
    }
    agent.events.push(e);
    agent.taskId = e.task_id ?? agent.taskId;
    agent.contextId = e.context_id ?? agent.contextId;
    const state = e.kind === "task" || e.kind === "status" ? (e.data.state as string) : null;
    if (state) {
      if (agent.states[agent.states.length - 1] !== state) agent.states.push(state);
      agent.current = state;
      const msg = e.kind === "status" ? (e.data.status?.message as A2AMessage | undefined) : undefined;
      if (msg) agent.statusMessage = msg;
      if (e.kind === "task") for (const a of (e.data.task?.artifacts ?? []) as A2AArtifact[]) agent.artifacts[a.artifactId] = a;
    }
    if (e.kind === "artifact") {
      const a = e.data.assembled as A2AArtifact;
      agent.artifacts[a.artifactId] = a;
    }
    if (e.kind === "message") agent.messages.push(e.data.message as A2AMessage);
    if (e.kind === "error") agent.error = e.data as ErrorData;
  }
  return turns;
}
```

`web/src/lib/parts.ts`:
```ts
import type { A2APart } from "./types";

export type PartKind = "text" | "raw" | "url" | "data" | "empty";

/** Which content field a part carries. */
export function partKind(p: A2APart): PartKind {
  if (p.text !== undefined) return "text";
  if (p.raw !== undefined) return "raw";
  if (p.url !== undefined) return "url";
  if (p.data !== undefined) return "data";
  return "empty";
}

/** Concatenate the text of all text parts. */
export function joinText(parts: A2APart[]): string {
  return parts.filter((p) => p.text !== undefined).map((p) => p.text).join("");
}

/** A data: URL for a raw (base64) part. */
export function dataUrl(p: A2APart): string {
  return `data:${p.mediaType ?? "application/octet-stream"};base64,${p.raw ?? ""}`;
}
```

`web/src/test/setup.ts`: `import "@testing-library/jest-dom/vitest";`

- [ ] **Step 4: Run** `cd web && pnpm install && pnpm test` → PASS
- [ ] **Step 5: Commit** `feat(web): scaffold, design tokens, API and WebSocket clients, timeline model`

---

### Task 13: Web — app shell, sidebar, connect dialog, agent page, About tab

**Files:**
- Create: `web/src/App.tsx`, `web/src/main.tsx`, `web/src/components/{Sidebar,ThemeToggle,Avatar,StatusPill,Switch,ConnectDialog,JsonView}.tsx`, `web/src/features/agent/{AgentPage,ConnectionMenu}.tsx`, `web/src/features/about/AboutView.tsx`
- Test: `web/src/components/ConnectDialog.test.tsx`, `web/src/features/about/AboutView.test.tsx`

**Interfaces:**
- Routes: `/` (empty state with "Connect an agent"), `/agents/:agentId/:tab?` (tab in `chat|about`, default `chat`).
- `ConnectDialog({open, onOpenChange, onConnected(agent)})`: step 1 URL → preview (`api.previewCard`), shows name, provider, skills count, signature status; step 2 interface radio list (unsupported bindings disabled with "coming soon"); "Connect" → `api.addAgent` then `api.patchAgent` when the chosen interface differs from the default.
- `ConnectionMenu({agent})`: popover listing interfaces (binding label, version, URL), check on the selected one; selecting calls `api.patchAgent`.
- `AboutView({agent})`: Overview (description, provider, version, input/output modes, docs link), "What it supports" (streaming, push notifications, extended card, extensions count, ways to connect), Skills grid with "Try" buttons that prefill the composer (via `onTry(example)` prop), Extensions list (read-only in Phase 1), signature status line, "View raw card" (JsonView in a dialog).

- [ ] **Step 1: Failing tests**

`ConnectDialog.test.tsx`:
```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { ConnectDialog } from "./ConnectDialog";

const preview = {
  card: { name: "Zoo agent", provider: { organization: "Acme" }, skills: [{ id: "a" }], capabilities: { streaming: true } },
  signature_status: "verified", signature_detail: null, exchange_ids: [],
  default_interface_url: "http://z/a2a",
  interfaces: [
    { url: "http://z/a2a", binding: "JSONRPC", protocol_version: "1.0", tenant: "", supported: true },
    { url: "http://z/g", binding: "GRPC", protocol_version: "1.0", tenant: "", supported: false },
  ],
};

describe("ConnectDialog", () => {
  it("previews the card, shows interfaces and connects", async () => {
    vi.spyOn(api, "previewCard").mockResolvedValue(preview as never);
    const add = vi.spyOn(api, "addAgent").mockResolvedValue({ id: "1", selected_interface_url: "http://z/a2a" } as never);
    const onConnected = vi.fn();
    render(<QueryClientProvider client={new QueryClient()}>
      <ConnectDialog open onOpenChange={() => {}} onConnected={onConnected} />
    </QueryClientProvider>);
    await userEvent.type(screen.getByLabelText(/agent address/i), "http://z");
    await userEvent.click(screen.getByRole("button", { name: /find agent/i }));
    expect(await screen.findByText("Zoo agent")).toBeInTheDocument();
    expect(screen.getByText(/signed card/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /gRPC/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(add).toHaveBeenCalledWith("http://z");
    expect(onConnected).toHaveBeenCalled();
  });

  it("shows a friendly error when the agent cannot be reached", async () => {
    const { ApiError } = await import("../lib/api");
    vi.spyOn(api, "previewCard").mockRejectedValue(new ApiError(422, "transport", "Could not load the agent card"));
    render(<QueryClientProvider client={new QueryClient()}>
      <ConnectDialog open onOpenChange={() => {}} onConnected={() => {}} />
    </QueryClientProvider>);
    await userEvent.type(screen.getByLabelText(/agent address/i), "http://nope");
    await userEvent.click(screen.getByRole("button", { name: /find agent/i }));
    expect(await screen.findByText(/couldn.t reach/i)).toBeInTheDocument();
  });
});
```

`AboutView.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AboutView } from "./AboutView";

const agent = {
  id: "1", name: "Zoo agent", base_url: "http://z", card_path: null, signature_status: "verified",
  signature_detail: null, selected_interface_url: "http://z/a2a", created_at: "", updated_at: "",
  interfaces: [{ url: "http://z/a2a", binding: "JSONRPC", protocol_version: "1.0", tenant: "", supported: true }],
  card: {
    name: "Zoo agent", description: "Reference agent", version: "1.0.0", provider: { organization: "Acme" },
    capabilities: { streaming: true }, defaultInputModes: ["text/plain"], defaultOutputModes: ["application/json"],
    skills: [{ id: "echo", name: "Echo", description: "Repeats", examples: ["echo hi"] }],
  },
};

describe("AboutView", () => {
  it("renders capabilities in plain language and lets you try a skill", async () => {
    const onTry = vi.fn();
    render(<AboutView agent={agent as never} onTry={onTry} />);
    expect(screen.getByText("Reference agent")).toBeInTheDocument();
    expect(screen.getByText("Live streaming").nextSibling).toHaveTextContent("Yes");
    expect(screen.getByText("Push notifications").nextSibling).toHaveTextContent("No");
    screen.getByRole("button", { name: /try: “echo hi”/i }).click();
    expect(onTry).toHaveBeenCalledWith("echo hi");
  });
});
```

- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement** the components. They follow the mockup's markup and classes 1:1: the sidebar (`.side`, `.brand`, `.nav`, `.agents`, `.agent`, `.add`, `.foot`, theme toggle storing `localStorage["a2aw-theme"]` inside try/catch), the main panel (`.main`, `.head`, `.status`, `.conn`, `.tabs`), the modal (`.scrim`, `.modal`, `.stepper`, `.inp`, `.found`, `.choice`) and the About cards. Use TanStack Query keys `["agents"]`, `["agent", id]`, `["conversations", agentId]`. Signature copy: verified → "signed card ✓", invalid → "signature invalid", unsigned → "not signed", unverifiable → "signature can't be checked". Error copy for the `transport` category: "We couldn't reach that address. Is the agent running?"; for `protocol`: "That address answered, but not with a valid A2A agent card."
- [ ] **Step 4: Run** `pnpm test` → PASS
- [ ] **Step 5: Commit** `feat(web): app shell, connect flow, agent page and About tab`

---

### Task 14: Web — Chat (turns, parts, artifacts, questions, composer, options)

**Files:**
- Create: `web/src/features/chat/{ChatView,Turn,TaskProgress,PartView,ArtifactCard,AskCard,EventLog,Composer,OptionsMenu}.tsx`, `web/src/features/chat/useConversation.ts`
- Test: `web/src/features/chat/PartView.test.tsx`, `TaskProgress.test.tsx`, `Composer.test.tsx`, `useConversation.test.ts`

**Interfaces:**
- `useConversation(conversationId)` → `{events, conversation, turns}`: loads `api.getConversation`, then subscribes to `conversation:<id>` from `last_seq`, merging events by `seq` (dedupe).
- `ChatView({agent})`: picks the latest conversation (or creates one on first send), renders turns, shows "New conversation" button and a conversation switcher (list of titles).
- `PartView({part})`: text (markdown when `mediaType` is `text/markdown`, else pre-wrapped), raw images/audio/video previews via data URL, other raw → download link with filename and size, url → link card (image preview when `mediaType` is image/*), data → collapsible JSON tree (`JsonView`).
- `TaskProgress({states, current})`: steps with check marks; current interrupted state in amber; labels from `stateLabel`.
- `AskCard({message, state, onQuickReply})`: "Waiting for you" (input_required) or "Sign-in needed" (auth_required); quick replies are not invented by the Workbench, so the card only shows the agent's message.
- `Composer({onSend, onStop, replying, busy, initialText})`: textarea (Enter sends, Shift+Enter newline), attach file (upload → `{kind:"file", blob_id}` chip), add JSON data (inline editor validated with `JSON.parse`), add URL part, Options popover (`OptionsMenu`), "Replying to the open question" pill when the task awaits input, "Stop task" button while a task is running.
- `OptionsMenu({value, onChange, agent})`: every `SendOptions` field: stream toggle (disabled with "This agent doesn't stream" when `capabilities.streaming` is false), return immediately, accepted formats (chips, with suggestions from the card's `defaultOutputModes`), history length (number or "default"), extensions (checkbox per card-declared extension URI; free-text add), message metadata (JSON editor), reference task ids.
- `EventLog({events})`: collapsed "Show what happened · N updates" list with relative times and plain sentences (`Task created`, `Working: “…”`, `Started sending “name”`, `Finished “name” (N pieces)`, `Asked you a question`, `Error: …`), each with a "raw" link that opens Inspect on that `exchange_id`.

- [ ] **Step 1: Failing tests**

`PartView.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PartView } from "./PartView";

describe("PartView", () => {
  it("renders plain text preserving whitespace", () => {
    render(<PartView part={{ text: "a\nb" }} />);
    expect(screen.getByText(/a\s+b/)).toHaveClass("whitespace-pre-wrap");
  });
  it("renders markdown when media type says so", () => {
    render(<PartView part={{ text: "**bold**", mediaType: "text/markdown" }} />);
    expect(screen.getByText("bold").tagName).toBe("STRONG");
  });
  it("renders raw images inline", () => {
    render(<PartView part={{ raw: "AAAA", mediaType: "image/png", filename: "p.png" }} />);
    expect(screen.getByRole("img", { name: "p.png" })).toHaveAttribute("src", "data:image/png;base64,AAAA");
  });
  it("renders other raw files as a download", () => {
    render(<PartView part={{ raw: "AAAA", mediaType: "application/pdf", filename: "x.pdf" }} />);
    expect(screen.getByRole("link", { name: /x\.pdf/ })).toHaveAttribute("download", "x.pdf");
  });
  it("renders url parts as links", () => {
    render(<PartView part={{ url: "https://e.com/a.html", filename: "a.html" }} />);
    expect(screen.getByRole("link", { name: /a\.html/ })).toHaveAttribute("href", "https://e.com/a.html");
  });
  it("renders data parts as JSON", () => {
    render(<PartView part={{ data: { ok: true } }} />);
    expect(screen.getByText(/"ok"/)).toBeInTheDocument();
  });
});
```

`TaskProgress.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TaskProgress } from "./TaskProgress";

describe("TaskProgress", () => {
  it("shows each state once in plain language and marks the current one", () => {
    render(<TaskProgress states={["submitted", "working", "input_required"]} current="input_required" />);
    expect(screen.getByText("Received")).toBeInTheDocument();
    expect(screen.getByText("Needs your input").closest("[data-current]")).toHaveAttribute("data-current", "true");
    expect(screen.getByTitle("input_required")).toBeInTheDocument();
  });
});
```

`Composer.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_OPTIONS } from "../../lib/types";
import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends text and data parts with options on Enter", async () => {
    const onSend = vi.fn();
    render(<Composer agent={{ card: { capabilities: { streaming: true } } } as never} onSend={onSend}
      onStop={() => {}} replying={false} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: /add json data/i }));
    await userEvent.type(screen.getByLabelText(/json data/i), '{{"n":1}');
    await userEvent.type(screen.getByPlaceholderText(/message/i), "hello{Enter}");
    expect(onSend).toHaveBeenCalledWith(
      [{ kind: "text", text: "hello" }, { kind: "data", data: { n: 1 } }], DEFAULT_OPTIONS);
  });

  it("blocks sending invalid JSON data", async () => {
    const onSend = vi.fn();
    render(<Composer agent={{ card: {} } as never} onSend={onSend} onStop={() => {}} replying={false} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: /add json data/i }));
    await userEvent.type(screen.getByLabelText(/json data/i), "{{bad");
    await userEvent.type(screen.getByPlaceholderText(/message/i), "x{Enter}");
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByText(/not valid json/i)).toBeInTheDocument();
  });

  it("disables streaming when the agent does not support it", async () => {
    render(<Composer agent={{ card: { capabilities: { streaming: false } } } as never} onSend={() => {}}
      onStop={() => {}} replying={false} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: /options/i }));
    expect(screen.getByRole("switch", { name: /stream replies live/i })).toBeDisabled();
  });
});
```

`useConversation.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { mergeEvents } from "./useConversation";

describe("mergeEvents", () => {
  it("dedupes by seq and keeps order", () => {
    const e = (seq: number) => ({ seq }) as never;
    expect(mergeEvents([e(1), e(2)], [e(2), e(3)]).map((x: { seq: number }) => x.seq)).toEqual([1, 2, 3]);
  });
});
```

- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement** the components using the mockup chat markup (`.thread`, `.msg`, `.bubble`, `.progress`, `.result`, `.ask`, `.more`, `.evs`, `.composer`, `.cbox`, `.cbar`, `.pop`, `.opt`, `.sw`, `.reply`, `.send`). `mergeEvents(a, b)` returns `[...new Map([...a, ...b].map(e => [e.seq, e])).values()].sort((x, y) => x.seq - y.seq)`. Sending: on first send without a conversation, `api.createConversation(agent.id)` then `api.sendMessage`. `replying` = conversation `task_state` is `input_required` or `auth_required`; `busy` = state `submitted`/`working`.
- [ ] **Step 4: Run** `pnpm test` → PASS
- [ ] **Step 5: Commit** `feat(web): chat with every part type, task progress, questions and send options`

---

### Task 15: Web — Inspect drawer

**Files:**
- Create: `web/src/features/inspect/InspectDrawer.tsx`, `web/src/features/inspect/useExchanges.ts`
- Test: `web/src/features/inspect/InspectDrawer.test.tsx`

**Interfaces:**
- `InspectDrawer({conversationId, open, onClose, focusExchangeId})`: lists exchanges (`api.listExchanges`, live-updated by the `exchanges:<id>` topic) with friendly names (`get_agent_card` → "Fetch agent card", `send_message` → "Send message" plus "(stream)" when frames exist, `cancel_task` → "Stop task", `http` → method + path), status, duration. Selecting one loads `api.getExchange` and shows tabs **Request** (method, URL, pretty JSON body), **Response** (status, pretty JSON body or SSE frames list, each frame's `data:` JSON pretty-printed with `+t ms`), **Headers** (request and response, redacted values shown as ••••). "Copy as cURL" builds a curl command from the request (redacted headers kept redacted). The drawer opens from the header **Inspect** button, from "View raw" on a result, and from event-log links.

- [ ] **Step 1: Failing test** `InspectDrawer.test.tsx`

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { InspectDrawer, friendlyOperation } from "./InspectDrawer";

describe("InspectDrawer", () => {
  it("names operations in plain language", () => {
    expect(friendlyOperation({ operation: "send_message", frame_count: 3 } as never)).toBe("Send message (stream)");
    expect(friendlyOperation({ operation: "get_agent_card", frame_count: 0 } as never)).toBe("Fetch agent card");
  });

  it("shows SSE frames of the selected exchange", async () => {
    vi.spyOn(api, "listExchanges").mockResolvedValue([
      { id: "e1", operation: "send_message", http_method: "POST", url: "http://z/a2a", started_at: "", status: 200, duration_ms: 12, error: null, frame_count: 1 },
    ]);
    vi.spyOn(api, "getExchange").mockResolvedValue({
      id: "e1", operation: "send_message", http_method: "POST", url: "http://z/a2a", started_at: "", status: 200,
      duration_ms: 12, error: null, frame_count: 1, request_headers: { authorization: "••••" },
      request_body: '{"method":"SendStreamingMessage"}', response_headers: {}, response_body: null,
      frames: [{ t_ms: 5, data: 'data: {"result":{"task":{"id":"t"}}}' }], truncated: false,
    });
    render(<QueryClientProvider client={new QueryClient()}>
      <InspectDrawer conversationId="c" open onClose={() => {}} />
    </QueryClientProvider>);
    await userEvent.click(await screen.findByText("Send message (stream)"));
    await userEvent.click(screen.getByRole("button", { name: "Response" }));
    expect(await screen.findByText(/\+5 ms/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Headers" }));
    expect(screen.getByText("••••")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2–4:** implement with the mockup drawer markup (`.drawer`, `.dh`, `.seg`, `.calls`, `.call`, `.dbody`, `.code`), then run `pnpm test` → PASS.
- [ ] **Step 5: Commit** `feat(web): inspect drawer with request, response, SSE frames and headers`

---

### Task 16: Build, packaging, Docker, CI, E2E, docs

**Files:**
- Create: `scripts/build.sh`, `scripts/dev.sh`, `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml`, `web/playwright.config.ts`, `web/e2e/connect-and-chat.spec.ts`, `README.md`, `CONTRIBUTING.md`, `NOTICE`, `docs/upstream-gaps.md`
- Modify: `CLAUDE.md` (commands section)

- [ ] **Step 1: `scripts/build.sh`**

```bash
#!/usr/bin/env bash
# Builds the web UI into the Python package and then the wheel.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$root/web" && pnpm install --frozen-lockfile && pnpm build)
rm -rf "$root/server/a2a_workbench/static"
cp -R "$root/web/dist" "$root/server/a2a_workbench/static"
(cd "$root/server" && uv build)
```

`scripts/dev.sh`:
```bash
#!/usr/bin/env bash
# Runs the API on :8484, the zoo agent on :9999 and the Vite dev server on :5173.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
trap 'kill 0' EXIT
(cd "$root/server" && uv run a2a-workbench fixtures --port 9999) &
(cd "$root/server" && uv run a2a-workbench serve --port 8484) &
(cd "$root/web" && pnpm dev) &
wait
```

- [ ] **Step 2: E2E** `web/playwright.config.ts`:
```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  use: { baseURL: "http://127.0.0.1:8585" },
  webServer: [
    { command: "cd ../server && uv run a2a-workbench fixtures --port 9898", url: "http://127.0.0.1:9898/.well-known/agent-card.json", reuseExistingServer: false },
    { command: "cd ../server && A2AW_HOME=$(mktemp -d) uv run a2a-workbench serve --port 8585", url: "http://127.0.0.1:8585/api/health", reuseExistingServer: false },
  ],
});
```

`web/e2e/connect-and-chat.spec.ts`:
```ts
import { expect, test } from "@playwright/test";

test("connect the zoo agent, stream a reply, inspect the wire", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /connect an agent/i }).first().click();
  await page.getByLabel(/agent address/i).fill("http://127.0.0.1:9898");
  await page.getByRole("button", { name: /find agent/i }).click();
  await expect(page.getByText("Zoo agent").first()).toBeVisible();
  await page.getByRole("button", { name: /^connect$/i }).click();
  await page.getByPlaceholder(/message/i).fill("stream");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Streaming in four pieces.")).toBeVisible();
  await expect(page.getByText("Done").first()).toBeVisible();
  await page.getByRole("button", { name: /inspect/i }).click();
  await expect(page.getByText("Send message (stream)")).toBeVisible();
  await page.getByPlaceholder(/message/i).fill("ask");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Which option should I pick: A or B?")).toBeVisible();
  await expect(page.getByText(/replying to the open question/i)).toBeVisible();
  await page.getByPlaceholder(/message/i).fill("B");
  await page.keyboard.press("Enter");
  await expect(page.getByText("You chose: B")).toBeVisible();
});
```
The E2E needs the built SPA: run `scripts/build.sh` (or `pnpm build` + copy) first.

- [ ] **Step 3: `Dockerfile`**

```dockerfile
FROM node:22-slim AS web
WORKDIR /src/web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.13-slim AS app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY server/ ./server/
COPY README.md ./
COPY --from=web /src/web/dist ./server/a2a_workbench/static
RUN cd server && uv pip install --system .
ENV A2AW_HOST=0.0.0.0 A2AW_HOME=/data
VOLUME /data
EXPOSE 8484
CMD ["a2a-workbench", "serve"]
```
`.dockerignore`: `**/node_modules`, `**/.venv`, `web/dist`, `server/a2a_workbench/static`, `.git`, `**/__pycache__`.

- [ ] **Step 4: CI** `.github/workflows/ci.yml` with jobs: `server` (setup uv, `uv sync`, `uv run ruff check`, `uv run ruff format --check`, `uv run pytest -q`), `web` (pnpm, `pnpm install --frozen-lockfile`, `pnpm lint`, `pnpm test`, `pnpm build`), `e2e` (needs both; installs Playwright chromium; `scripts/build.sh` minus the wheel; `pnpm e2e`), `docker` (`docker build .`).

- [ ] **Step 5: Docs.** `README.md`: what it is, the screenshot placeholder replaced by the mockup link, quick start (`uvx a2a-workbench serve`, `docker run -p 8484:8484 ghcr.io/mittal0802/a2a-workbench`), try it with `a2a-workbench fixtures`, CLI examples (`card`, `send --json`), development (`scripts/dev.sh`, tests), license. `CONTRIBUTING.md`: setup, `git config core.hooksPath .githooks`, conventional commits, the three CLAUDE.md rules. `NOTICE`: "A2A Workbench, Copyright 2026 Keshav Mittal". `docs/upstream-gaps.md`: heading plus the format for entries (what's missing, why, proposed API, status). CLAUDE.md gets a **Commands** section listing `cd server && uv sync`, `uv run pytest`, `uv run ruff check .`, `cd web && pnpm install && pnpm test`, `scripts/dev.sh`, `scripts/build.sh`, `pnpm e2e`.

- [ ] **Step 6: Verify everything:** `cd server && uv run pytest -q && uv run ruff check .`; `cd web && pnpm test && pnpm build`; `scripts/build.sh`; `cd web && pnpm exec playwright install chromium && pnpm e2e`; `uvx --from server/dist/*.whl a2a-workbench --help`.
- [ ] **Step 7: Commit** `chore: build scripts, docker image, CI, e2e test and docs`

---

## Self-Review

- **Spec coverage (Phase 1 scope, §12):** scaffold and CI (T1, T16); single-process server serving the SPA (T9); SQLite store (T2); design tokens and shell with theme toggle (T12, T13); connect flow with signature verification and interface choice (T5, T6, T13); About tab (T13); chat with send and stream, all Part types, input_required reply, stop task, Options menu covering every `SendMessageConfiguration` field plus extensions, metadata and references (T7, T8, T14); Inspect with WireRecorder (T4, T15); CLI `serve/agents/card/send` with `--json`/NDJSON and exit codes (T11); zoo `compliant` (T3); uvx/Docker packaging (T16). HTTP+JSON comes along for free through the SDK (T6), with gRPC deferred to Phase 2 as planned.
- **Placeholders:** none. UI component bodies follow the mockup markup referenced by file. Tests define the behaviour.
- **Type consistency:** `TimelineEvent` fields match between Python (T7) and TS (T12); `SendOptions` field names match between `options.py` and `types.ts` (`history_length`, `accepted_output_modes`, `return_immediately`, `extensions`, `message_metadata`, `reference_task_ids`); topic names `conversation:<id>` and `exchanges:<id>` match between T8, T4, T10 and T12.
- **Review Focus:** each of the 5 items has a named test in its owning task.
