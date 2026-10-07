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
    ex = Exchange(
        id="e1",
        operation="send_message",
        http_method="POST",
        url="http://x/a2a",
        started_at=datetime.now(UTC),
        conversation_id="c1",
        status=200,
    )
    async with bus.subscription("exchanges:c1") as q:
        await store(ex)
        msg = q.get_nowait()
    assert msg["type"] == "exchange" and msg["exchange"]["id"] == "e1"
    assert (await store.get("e1"))["url"] == "http://x/a2a"
    assert [e["id"] for e in await store.list(conversation_id="c1")] == ["e1"]
    assert await store.get("missing") is None
    await db.dispose()
