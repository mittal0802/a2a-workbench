import pytest


async def test_compliant_zoo_passes_b_c_e(health_of):
    _, run = await health_of(["B", "C", "E"], interfaces="all")
    bad = [
        (r.check_id, r.interface, r.status)
        for r in run.results
        if r.status not in ("pass", "not_supported")
    ]
    # The SDK's gRPC server does not validate A2A-Version (docs/upstream-gaps.md),
    # so the SDK-built zoo really violates A2A §3.6.2 there.
    grpc = [i for i in run.interfaces if not i.startswith("http")]
    assert bad == [("B3.version_unsupported", grpc[0], "fail")]


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
