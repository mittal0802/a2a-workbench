import pytest

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.core.health.model import Check, passed, violated
from a2a_workbench.core.health.runner import HealthService


async def _pass(ctx):
    return passed("ok", "ok")


async def _violate(ctx):
    return violated("x", "y")


async def _boom(ctx):
    raise RuntimeError("probe exploded")


async def _send(ctx):
    events = await ctx.send("echo evidence")
    return violated("artifact", f"{len(events)} events")


def _check(cid, run, *, level="must", area="C", applies=None, per_interface=True):
    return Check(
        id=cid,
        area=area,
        title=cid,
        spec_ref=f"A2A §{cid}",
        level=level,
        fix_hint="fix it",
        run=run,
        applies=applies or (lambda ctx: None),
        per_interface=per_interface,
    )


@pytest.fixture
async def agent(wb, zoo):
    return await wb.agents.add(zoo.base_url)


async def _run(svc, agent_id, **kw):
    events = [e async for e in svc.run(agent_id, **kw)]
    return events, await svc.get(events[0].run_id)


async def test_statuses_levels_and_score(wb, agent):
    svc = HealthService(
        wb,
        checks=[
            _check("p1", _pass),
            _check("p2", _pass),
            _check("w1", _violate, level="should"),
            _check("f1", _violate),
            _check("n1", _pass, applies=lambda ctx: "not declared"),
        ],
    )
    events, run = await _run(svc, agent.id)
    by = {r.check_id: r for r in run.results}
    assert [by[c].status for c in ("p1", "p2", "w1", "f1", "n1")] == [
        "pass",
        "pass",
        "warn",
        "fail",
        "not_supported",
    ]
    assert by["n1"].actual == "not declared"
    assert run.counts == {"pass": 2, "warn": 1, "fail": 1, "not_supported": 1, "error": 0}
    assert run.score == round(100 * (2 + 0.5) / 4) and run.status == "done"
    assert events[0].kind == "started" and events[-1].kind == "finished"


async def test_not_applicable_is_not_counted(wb, agent):
    svc = HealthService(
        wb, checks=[_check("p", _pass), _check("n", _violate, applies=lambda ctx: "no")]
    )
    _, run = await _run(svc, agent.id)
    assert run.score == 100


async def test_check_error_is_isolated(wb, agent):
    svc = HealthService(wb, checks=[_check("boom", _boom), _check("p", _pass)])
    _, run = await _run(svc, agent.id)
    by = {r.check_id: r for r in run.results}
    assert by["boom"].status == "error" and "probe exploded" in by["boom"].actual
    assert by["p"].status == "pass" and run.score == 100


async def test_evidence_exchange_ids_are_collected(wb, agent):
    svc = HealthService(wb, checks=[_check("ev", _send)])
    _, run = await _run(svc, agent.id)
    result = run.results[0]
    assert result.exchange_ids
    for eid in result.exchange_ids:
        assert (await wb.exchanges.get(eid))["operation"] == "send_message"


async def test_runs_per_interface_and_once_for_card_checks(wb, agent):
    seen = []

    async def where(ctx):
        seen.append(ctx.binding)
        return passed("", ctx.binding)

    svc = HealthService(
        wb, checks=[_check("each", where), _check("card", _pass, area="A", per_interface=False)]
    )
    _, run = await _run(svc, agent.id, interfaces="all")
    assert sorted(seen) == ["GRPC", "HTTP+JSON", "JSONRPC"]
    assert [r.check_id for r in run.results].count("card") == 1
    assert {r.interface for r in run.results if r.check_id == "each"} == {
        i.url for i in agent.interfaces
    }
    assert (await wb.agents.get(agent.id)).selected_interface_url == agent.selected_interface_url


async def test_area_filter_and_listing(wb, agent):
    svc = HealthService(wb, checks=[_check("c", _pass, area="C"), _check("f", _pass, area="F")])
    _, run = await _run(svc, agent.id, areas=["F"])
    assert [r.check_id for r in run.results] == ["f"]
    assert [r.id for r in await svc.list(agent_id=agent.id)] == [run.id]


async def test_probe_tasks_are_tracked(wb, agent):
    async def creates(ctx):
        await ctx.send("echo t")
        return passed("", ",".join(ctx.created_tasks))

    svc = HealthService(wb, checks=[_check("t", creates)])
    _, run = await _run(svc, agent.id)
    assert run.results[0].actual
    conv = await wb.conversations.get(run.conversation_id)
    assert conv.origin == "health"
    assert SendOptions and TextPartInput
