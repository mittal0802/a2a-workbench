import asyncio
import json

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.faults.profile import FaultProfile
from a2a_workbench.core.health.runner import HealthService
from a2a_workbench.fixtures.auth import ZOO_SECRETS
from a2a_workbench.fixtures.runner import ZooServer


async def _run(wb, zoo, areas, **kw):
    agent = await wb.agents.add(zoo.base_url)
    return agent, await _again(wb, agent, areas, **kw)


async def _again(wb, agent, areas, **kw):
    events = [e async for e in wb.health.run(agent.id, areas=areas, **kw)]
    return await wb.health.get(events[0].run_id)


async def test_secrets_never_reach_results(wb):
    async with ZooServer(auth="apikey-query", breaks={"dead-interface"}) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        await wb.auth.set_credential(
            agent.id,
            card_from_json(agent.card),
            "apiKeyQuery",
            "api_key",
            {"value": ZOO_SECRETS["api_key"]},
        )
        run = await _again(wb, agent, ["B", "F"], interfaces="all")
        report = json.dumps(await wb.health.report_json(run.id)) + await wb.health.report_html(
            run.id
        )
    assert any(r.status == "fail" for r in run.results)
    assert ZOO_SECRETS["api_key"] not in report


async def test_workbench_side_failures_are_errors_not_fails(wb, monkeypatch):
    from a2a_workbench.core.errors import AgentCallError

    async def broken(*a, **k):
        raise AgentCallError({"category": "workbench", "message": "KeyError: oops"})

    async with ZooServer() as zoo:
        agent = await wb.agents.add(zoo.base_url)
        monkeypatch.setattr(wb.tasks, "get", broken)
        run = await _again(wb, agent, ["F"])
    f2 = next(r for r in run.results if r.check_id == "F2.get_unknown")
    assert f2.status == "error" and "oops" in f2.actual


async def test_sdk_unsupported_calls_are_not_supported(wb, monkeypatch):
    from a2a_workbench.core.errors import AgentCallError

    async def unsupported(*a, **k):
        raise AgentCallError(
            {"category": "workbench", "message": "NotImplementedError: ListTasks is not supported"}
        )

    async with ZooServer() as zoo:
        agent = await wb.agents.add(zoo.base_url)
        monkeypatch.setattr(wb.tasks, "list", unsupported)
        run = await _again(wb, agent, ["F"])
    f4 = next(r for r in run.results if r.check_id == "F4.list_context_filter")
    assert f4.status == "not_supported", f4


async def test_missing_sign_in_is_not_supported(wb):
    async with ZooServer(auth="bearer", grpc=False) as zoo:
        _, run = await _run(wb, zoo, ["A", "F", "G"])
    bad = [(r.check_id, r.actual) for r in run.results if r.status in ("fail", "warn", "error")]
    assert bad == []


async def test_v03_interfaces_are_not_judged_by_v1_rules(wb):
    async with ZooServer(legacy=True) as zoo:
        _, run = await _run(wb, zoo, None, interfaces="all")
    bad = [(r.check_id, r.interface, r.actual) for r in run.results if r.status in ("fail", "warn")]
    assert bad == []
    assert any("0.3" in r.actual for r in run.results if r.status == "not_supported")


async def test_every_non_pass_result_has_evidence(wb):
    async with ZooServer(
        breaks={"card-no-cache", "wrong-error-codes", "card-missing-fields"}
    ) as zoo:
        _, run = await _run(wb, zoo, ["A", "K"])
    flagged = [r for r in run.results if r.status in ("fail", "warn")]
    assert {"A2.card_required_fields", "A6.card_caching", "K1.errors_mapping"} <= {
        r.check_id for r in flagged
    }
    assert [r.check_id for r in flagged if not r.exchange_ids] == []


async def test_checks_use_the_live_card(wb):
    async with ZooServer(streaming=True) as zoo:
        agent = await wb.agents.add(zoo.base_url)
    async with ZooServer(port=zoo.port, streaming=False):
        run = await _again(wb, agent, ["G"])
    g1 = next(r for r in run.results if r.check_id == "G1.stream_capability")
    assert g1.status == "pass", g1


async def test_faults_apply_to_probes(wb):
    profile = FaultProfile.model_validate(
        {"rules": [{"kind": "http_status", "mode": "always", "params": {"code": 503}}]}
    )
    async with ZooServer() as zoo:
        _, run = await _run(wb, zoo, ["F"], faults=profile)
    assert any("503" in r.actual for r in run.results), [r.actual for r in run.results]


async def test_push_crud_uses_a_reachable_webhook(wb):
    async with ZooServer() as zoo:
        _, run = await _run(wb, zoo, ["H"])
        h2 = next(r for r in run.results if r.check_id == "H2.push_crud")
        assert h2.status == "pass"
        sent = [await wb.exchanges.get(i) for i in h2.exchange_ids]
    bodies = " ".join(x.get("request_body") or "" for x in sent)
    assert "invalid" not in bodies and "/hooks/" in bodies


async def test_close_stops_runs_and_stale_runs_are_stopped_on_start(tmp_path, monkeypatch):
    from a2a_workbench.core.config import Settings
    from a2a_workbench.core.workbench import Workbench

    monkeypatch.setenv("A2AW_HOME", str(tmp_path))
    async with ZooServer() as zoo:
        async with Workbench.open(Settings()) as wb:
            agent = await wb.agents.add(zoo.base_url)
            run_id = await wb.health.start(agent.id)
        async with Workbench.open(Settings()) as wb:
            assert (await wb.health.get(run_id)).status == "stopped"


async def test_stale_running_rows_are_marked_stopped(wb):
    from a2a_workbench.core.store.models import HealthRun

    async with wb.db.sessions() as session:
        session.add(HealthRun(id="stale", agent_id="a", card_url="x", status="running"))
        await session.commit()
    await HealthService(wb).recover()
    assert (await wb.health.get("stale")).status == "stopped"


async def test_new_broken_variants_are_detected(health_of):
    for brk, check, kw in [
        ("get-returns-other-task", "F1.get_task", {}),
        ("push-config-dropped", "H2.push_crud", {}),
        ("extended-unsupported", "A7.extended_capability", {}),
    ]:
        results, _ = await health_of([check[0]], breaks=[brk], **kw)
        assert results[check].status == "fail", (brk, results[check])
    await asyncio.sleep(0)
