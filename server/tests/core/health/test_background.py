import asyncio

import pytest

from a2a_workbench.core.health.runner import RunNotFoundError
from a2a_workbench.fixtures.runner import ZooServer


async def _until(predicate, attempts=600):
    for _ in range(attempts):
        if result := await predicate():
            return result
        await asyncio.sleep(0.1)
    raise AssertionError("timed out")


async def test_start_runs_in_background_and_findings_lists_problems(wb):
    async with ZooServer(breaks={"get-unknown-returns"}) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        run_id = await wb.health.start(agent.id, areas=["F"])
        assert wb.health.is_running(run_id)

        async def done():
            run = await wb.health.get(run_id)
            return run if run.status != "running" else None

        run = await _until(done)
    assert run.status == "done" and not wb.health.is_running(run_id)
    found = await wb.health.findings(agent_id=agent.id)
    assert [f.check_id for f in found] == ["F2.get_unknown"]
    assert await wb.health.findings(run_id=run_id, statuses=("pass",))


async def test_stop_marks_the_run_stopped(wb):
    async with ZooServer() as zoo:
        agent = await wb.agents.add(zoo.base_url)
        run_id = await wb.health.start(agent.id)
        assert await wb.health.stop(run_id) is True
        run = await wb.health.get(run_id)
    assert run.status == "stopped"
    assert await wb.health.stop(run_id) is False


async def test_findings_without_runs(wb):
    with pytest.raises(RunNotFoundError):
        await wb.health.findings(agent_id="nobody")
