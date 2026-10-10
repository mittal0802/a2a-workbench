import pytest


async def test_compliant_zoo_passes_f_and_g(health_of):
    results, run = await health_of(["F", "G"], interfaces="all")
    bad = [
        (r.check_id, r.interface, r.status, r.actual)
        for r in run.results
        if r.status not in ("pass", "not_supported")
    ]
    assert bad == []
    assert results["G1.stream_capability"].status == "not_supported"


async def test_undeclared_streaming_is_checked(health_of):
    results, _ = await health_of(["G"], streaming=False)
    assert results["G1.stream_capability"].status == "pass", results["G1.stream_capability"]
    assert results["G2.stream_first_event"].status == "not_supported"


@pytest.mark.parametrize(
    "brk,check,kw",
    [
        ("get-unknown-returns", "F2.get_unknown", {}),
        ("get-history-ignored", "F3.get_history_length", {}),
        ("list-ignores-context", "F4.list_context_filter", {}),
        ("list-artifacts", "F6.list_artifacts_omitted", {}),
        ("list-order", "F7.list_order", {}),
        ("cancel-terminal-ok", "F8.cancel_terminal", {}),
        ("cancel-unknown-ok", "F9.cancel_unknown", {}),
        ("stream-status-first", "G2.stream_first_event", {}),
        ("stream-no-close", "G3.stream_closes", {}),
        ("subscribe-no-task-first", "G4.subscribe_task_first", {}),
        ("subscribe-terminal-ok", "G5.subscribe_terminal", {}),
        ("streaming-undeclared-works", "G1.stream_capability", {"streaming": False}),
    ],
)
async def test_detects_task_and_stream_violations(health_of, brk, check, kw):
    results, _ = await health_of([check[0]], breaks=[brk], **kw)
    assert results[check].status == "fail", results[check]


async def test_cancel_probe_only_uses_run_tasks(wb, health_of):
    from a2a_workbench.core.conversations.options import SendOptions
    from a2a_workbench.core.conversations.parts import TextPartInput
    from a2a_workbench.fixtures.runner import ZooServer

    async with ZooServer(grpc=False) as zoo:
        agent = await wb.agents.add(zoo.base_url)
        conv = await wb.conversations.create(agent.id)
        mine = [
            e
            async for e in wb.conversations.send(
                conv.id,
                [TextPartInput(text="slow 30")],
                SendOptions(stream=False, return_immediately=True),
            )
        ]
        my_task = next(e.task_id for e in mine if e.task_id)
        events = [e async for e in wb.health.run(agent.id, areas=["F"])]
        run = await wb.health.get(events[0].run_id)
        assert all(my_task not in r.actual for r in run.results)
        assert (await wb.tasks.get(agent.id, my_task))["state"] == "working"
