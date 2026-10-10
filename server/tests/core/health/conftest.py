import pytest

from a2a_workbench.fixtures.runner import ZooServer


@pytest.fixture
def health_of(wb):
    """Run the checks of ``areas`` against a zoo with ``breaks``; return ({id: result}, run)."""

    async def run(areas, *, breaks=(), interfaces="selected", **zoo_kw):
        async with ZooServer(breaks=set(breaks), **zoo_kw) as zoo:
            agent = await wb.agents.add(zoo.base_url)
            events = [e async for e in wb.health.run(agent.id, areas=areas, interfaces=interfaces)]
            run = await wb.health.get(events[0].run_id)
        out = {}
        for r in run.results:
            out.setdefault(r.check_id, r)
        return out, run

    return run
