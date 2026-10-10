import pytest


async def test_compliant_zoo_passes_l(health_of):
    results, run = await health_of(["L"], interfaces="all")
    bad = [
        (r.check_id, r.interface, r.status, r.actual)
        for r in run.results
        if r.status not in ("pass", "not_supported")
    ]
    assert bad == []
    for check in (
        "L1.resilience_resubscribe",
        "L2.resilience_independent",
        "L3.resilience_multi_stream",
    ):
        assert results[check].status == "pass", results[check]


async def test_l_needs_streaming(health_of):
    results, _ = await health_of(["L"], streaming=False)
    assert all(r.status == "not_supported" for r in results.values())


@pytest.mark.parametrize(
    "brk,check",
    [
        ("subscribe-no-task-first", "L1.resilience_resubscribe"),
        ("cancel-on-disconnect", "L2.resilience_independent"),
        ("single-subscriber", "L3.resilience_multi_stream"),
    ],
)
async def test_detects_resilience_violations(health_of, brk, check):
    results, _ = await health_of(["L"], breaks=[brk])
    assert results[check].status == "fail", results[check]
