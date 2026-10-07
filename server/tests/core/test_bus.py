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


async def test_publish_without_subscribers_is_dropped():
    EventBus().publish("nobody", {"n": 1})
