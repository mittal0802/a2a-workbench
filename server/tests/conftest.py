import asyncio
import contextlib
import os
import uuid

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(request, tmp_path, monkeypatch):
    monkeypatch.setenv("A2AW_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("A2AW_DATABASE_URL", raising=False)
    on_postgres = os.environ.get("A2AW_TEST_ALL_ON_POSTGRES") and os.environ.get(
        "A2AW_TEST_POSTGRES_URL"
    )
    if on_postgres and not request.node.get_closest_marker("default_database"):
        with _postgres_database() as url:
            monkeypatch.setenv("A2AW_DATABASE_URL", url)
            yield
        return
    yield


@contextlib.contextmanager
def _postgres_database():
    """A new, empty Postgres database for one test, dropped afterwards."""
    import asyncpg
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["A2AW_TEST_POSTGRES_URL"])
    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    name = f"t_{uuid.uuid4().hex[:12]}"

    async def admin(sql):
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(admin(f'DROP DATABASE "{name}" WITH (FORCE)'))


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


@pytest.fixture(scope="session")
def custom_path_zoo():
    from a2a_workbench.fixtures.runner import ZooServer

    with ZooServer(card_path="/agents/zoo/card.json") as server:
        yield server


@pytest.fixture(scope="session")
def legacy_zoo():
    from a2a_workbench.fixtures.runner import ZooServer

    with ZooServer(legacy=True) as server:
        yield server
