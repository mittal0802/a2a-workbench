import pytest


async def test_compliant_zoo_passes_b_c_e(health_of):
    results, _ = await health_of(["B", "C", "E"], interfaces="all")
    bad = {
        k: (v.status, v.actual)
        for k, v in results.items()
        if v.status not in ("pass", "not_supported")
    }
    assert bad == {}


@pytest.mark.parametrize(
    "brk,check,status",
    [
        ("dead-interface", "B1.interface_answers", "fail"),
        ("split-stores", "B2.interfaces_equivalent", "fail"),
        ("no-context", "C3.context_generated", "fail"),
        ("unknown-task-ok", "C4.unknown_task", "fail"),
        ("mismatch-ok", "C5.context_task_mismatch", "fail"),
        ("terminal-accepts", "C6.terminal_task_message", "fail"),
        ("history-ignored", "C7.history_zero", "warn"),
        ("blocking-working", "C2.send_blocking_state", "fail"),
        ("message-output", "E1.results_as_artifacts", "warn"),
    ],
)
async def test_detects_messaging_violations(wb, health_of, brk, check, status):
    _, run = await health_of(["B", "C", "E"], breaks=[brk], interfaces="all")
    statuses = [r.status for r in run.results if r.check_id == check]
    assert status in statuses, [
        (r.interface, r.status, r.actual) for r in run.results if r.check_id == check
    ]
