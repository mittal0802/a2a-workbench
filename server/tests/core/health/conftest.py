import pytest

from a2a_workbench.fixtures.runner import ZooServer


@pytest.fixture
def health_of(wb):
    """Run the checks of ``areas`` against a zoo with ``breaks``.

    Returns ({check id: its worst result over the tested interfaces}, run).
    """

    async def run(areas, *, breaks=(), interfaces="selected", **zoo_kw):
        async with ZooServer(breaks=set(breaks), **zoo_kw) as zoo:
            agent = await wb.agents.add(zoo.base_url)
            events = [e async for e in wb.health.run(agent.id, areas=areas, interfaces=interfaces)]
            run = await wb.health.get(events[0].run_id)
        rank = {"fail": 0, "error": 1, "warn": 2, "pass": 3, "not_supported": 4}
        out = {}
        for r in run.results:
            if r.check_id not in out or rank[r.status] < rank[out[r.check_id].status]:
                out[r.check_id] = r
        return out, run

    return run
