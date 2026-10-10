import asyncio

import pytest
import uvicorn

from a2a_workbench.api.app import create_app
from a2a_workbench.core.config import Settings
from a2a_workbench.fixtures.runner import ZooServer, free_port


async def test_compliant_zoo_passes_h_j_k(health_of):
    results, run = await health_of(["H", "J", "K"], interfaces="all")
    bad = [
        (r.check_id, r.interface, r.status, r.actual)
        for r in run.results
        if r.status not in ("pass", "not_supported")
    ]
    assert bad == []
    for check in ("H2.push_crud", "H3.push_delete_idempotent", "K1.errors_mapping"):
        assert results[check].status == "pass", results[check]
    assert results["H1.push_capability"].status == "not_supported"
    assert results["J1.extension_required"].status == "not_supported"


async def test_undeclared_push_is_checked(health_of):
    results, _ = await health_of(["H"], push=False)
    assert results["H1.push_capability"].status == "pass", results["H1.push_capability"]
    assert results["H2.push_crud"].status == "not_supported"


async def test_required_extension_is_checked(health_of):
    results, _ = await health_of(["J"], required_extension=True)
    assert results["J1.extension_required"].status == "pass", results["J1.extension_required"]


async def test_auth_enforcing_zoo_passes_i(health_of):
    results, _ = await health_of(["I"], auth="bearer")
    for check in ("I1.auth_rejects_anonymous", "I2.auth_rejects_wrong", "I3.auth_challenge"):
        assert results[check].status == "pass", results[check]


async def test_open_agent_skips_i(health_of):
    results, _ = await health_of(["I"])
    assert results["I1.auth_rejects_anonymous"].status == "not_supported"


@pytest.mark.parametrize(
    "brk,check,kw",
    [
        ("push-undeclared-works", "H1.push_capability", {"push": False}),
        ("push-delete-not-idempotent", "H3.push_delete_idempotent", {}),
        ("auth-not-enforced", "I1.auth_rejects_anonymous", {}),
        ("auth-not-enforced", "I2.auth_rejects_wrong", {}),
        ("extension-not-enforced", "J1.extension_required", {"required_extension": True}),
        ("wrong-error-codes", "K1.errors_mapping", {}),
    ],
)
async def test_detects_push_security_and_error_violations(health_of, brk, check, kw):
    results, _ = await health_of([check[0]], breaks=[brk], **kw)
    assert results[check].status == "fail", results[check]


async def test_detects_missing_challenge(health_of):
    results, _ = await health_of(["I"], breaks=["no-challenge"], auth="bearer")
    assert results["I3.auth_challenge"].status == "warn", results["I3.auth_challenge"]


@pytest.mark.parametrize("interface", ["selected", "all"])
async def test_wrong_error_codes_fail_on_every_binding(health_of, interface):
    _, run = await health_of(["K"], breaks=["wrong-error-codes"], interfaces=interface)
    k1 = [r for r in run.results if r.check_id == "K1.errors_mapping"]
    assert k1 and all(r.status == "fail" for r in k1)


@pytest.fixture
async def served(monkeypatch):
    """A running Workbench server, so agents can deliver push notifications to it."""
    port = free_port()
    monkeypatch.setenv("A2AW_PORT", str(port))
    app = create_app(Settings())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    yield app.state.workbench
    server.should_exit = True
    await task


async def _h4(wb, **zoo_kw):
    async with ZooServer(**zoo_kw) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        events = [e async for e in wb.health.run(agent.id, areas=["H"])]
        run = await wb.health.get(events[0].run_id)
    return next(r for r in run.results if r.check_id == "H4.push_delivery_auth")


async def test_delivery_auth_passes_when_reachable(served):
    result = await _h4(served)
    assert result.status == "pass", result


async def test_detects_push_without_auth(served):
    result = await _h4(served, breaks={"push-no-auth"})
    assert result.status == "fail", result
    assert result.exchange_ids or result.actual
