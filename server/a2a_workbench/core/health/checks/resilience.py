"""Area L — Resilience: tasks outlive their streams (A2A §3.1.6, §3.5.2)."""

import asyncio

from a2a.client import ClientCallContext
from a2a.types import SubscribeToTaskRequest

from a2a_workbench.core.a2a_json import state_name
from a2a_workbench.core.connection.client import open_client, select_interface
from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.faults.profile import FaultProfile
from a2a_workbench.core.health.checks.common import call, describe
from a2a_workbench.core.health.context import TERMINAL_STATES, RunContext
from a2a_workbench.core.health.model import Check, Outcome, passed, skipped, violated
from a2a_workbench.core.health.registry import register

SETTLE_S = 30.0
RUNNING = frozenset({"submitted", "working"})
CHECK_AFTER_S = 0.4
DROP = FaultProfile.model_validate(
    {
        "name": "health_drop",
        "description": "Drop the streamed reply after its first event.",
        "rules": [
            {
                "kind": "drop_stream",
                "match": {"operation": "send_message"},
                "params": {"after_events": 1},
            }
        ],
    }
)


def _streams(ctx: RunContext) -> str | None:
    return None if ctx.capabilities.streaming else "the card does not declare streaming"


async def _state_soon(ctx: RunContext, task_id: str) -> str | None:
    """The task's state a moment from now (None if GetTask fails)."""
    await asyncio.sleep(CHECK_AFTER_S)
    task, error = await call(ctx.wb.tasks.get(ctx.agent.id, task_id))
    return None if error else task.get("state")


async def _still_running(ctx: RunContext, task_id: str) -> bool:
    """Whether the task is submitted or working a moment from now."""
    return await _state_soon(ctx, task_id) in RUNNING


async def _dropped(ctx: RunContext) -> tuple[str, str, str] | Outcome:
    """Stream probe texts, dropping each stream after one event, until a task is left running.

    A task canceled right after its stream dropped also ends the search.
    Returns (conversation id, task id, state shortly after the drop), or an
    Outcome when every probe task finished (or waits for input) too soon to test.
    """
    if "dropped" in ctx.cache:
        return ctx.cache["dropped"]
    found: tuple[str, str, str] | Outcome = skipped(
        "every probe finished before its stream could be dropped"
    )
    for text in ctx.probe_texts()[:6]:
        conv = await ctx.new_conversation()
        events = await ctx.send(
            text,
            options=SendOptions(stream=True, inherit_ids=False, faults=DROP),
            conversation_id=conv,
        )
        if any(e.kind == "error" and (e.data or {}).get("category") == "auth" for e in events):
            found = skipped("the agent requires sign-in; add credentials to check this")
            break
        task_id = next((e.task_id for e in events if e.task_id), None)
        dropped = any(e.kind == "connection_lost" for e in events)
        if not (task_id and dropped):
            continue
        state = await _state_soon(ctx, task_id)
        if state in RUNNING or state == "canceled":
            found = (conv, task_id, state)
            break
    ctx.cache["dropped"] = found
    return found


async def _resubscribe(ctx: RunContext) -> Outcome:
    dropped = await _dropped(ctx)
    if isinstance(dropped, Outcome):
        return dropped
    conv, task_id, state = dropped
    if state == "canceled":
        return skipped(f"task {task_id} was canceled when its stream dropped (see L2)")
    expected = "SubscribeToTask after a dropped stream starts with the current Task"
    events = [e async for e in ctx.wb.conversations.resubscribe(conv, force=True)]
    recovered = next((e for e in events if e.kind == "recovered"), None)
    error = next((e for e in events if e.kind == "error"), None)
    if recovered is None:
        if error is not None:
            message = (error.data or {}).get("message", "")
            if "already finished" in message:
                return skipped(f"task {task_id} finished before the resubscribe")
            return violated(expected, describe(error.data))
        return violated(expected, f"stream ended without a terminal state ({len(events)} events)")
    data = recovered.data
    if not data.get("snapshot_first"):
        return violated(expected, f"first event was {data.get('first_event')}")
    return passed(
        expected,
        f"Task first, then {data.get('state_after')}; "
        f"{data.get('duplicate_events', 0)} repeated event(s)",
    )


async def _independent(ctx: RunContext) -> Outcome:
    dropped = await _dropped(ctx)
    if isinstance(dropped, Outcome):
        return dropped
    _, task_id, state = dropped
    expected = f"task {task_id} keeps running after its stream drops"
    if state == "canceled":
        return violated(expected, "the task was canceled when the stream dropped")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SETTLE_S
    state = None
    while loop.time() < deadline:
        task, error = await call(ctx.wb.tasks.get(ctx.agent.id, task_id))
        if error is not None:
            return violated(expected, f"GetTask: {describe(error)}")
        state = task.get("state")
        if state in TERMINAL_STATES or state in ("input_required", "auth_required"):
            break
        await asyncio.sleep(0.3)
    if state == "canceled":
        return violated(expected, "the task was canceled when the stream dropped")
    if state not in TERMINAL_STATES and state not in ("input_required", "auth_required"):
        return skipped(f"task {task_id} still {state} after {SETTLE_S:.0f}s")
    return passed(expected, f"the task reached {state}")


async def _collect(ctx: RunContext, task_id: str, started: asyncio.Event) -> list[tuple[str, str]]:
    """Subscribe to the task through the SDK; return (kind, state or artifact) per event.

    Stops at the first terminal or interrupted state.
    """
    plan = await ctx.wb.auth.plan(ctx.agent.id, ctx.card)
    iface = select_interface(ctx.card, ctx.interface_url)
    client = await open_client(ctx.card, iface, ctx.wb.exchanges, streaming=True, auth=plan)
    out: list[tuple[str, str]] = []
    async with client:
        async for resp in client.subscribe(
            SubscribeToTaskRequest(id=task_id),
            context=ClientCallContext(service_parameters=plan.headers),
        ):
            kind = resp.WhichOneof("payload")
            started.set()
            if kind == "status_update":
                out.append((kind, state_name(resp.status_update.status.state)))
            elif kind == "artifact_update":
                part = resp.artifact_update.artifact
                out.append((kind, f"{part.artifact_id}:{len(part.parts)}"))
            elif kind == "task":
                out.append((kind, state_name(resp.task.status.state)))
            if out and out[-1][0] != "artifact_update" and out[-1][1] not in RUNNING:
                break
    return out


def _after_task(events: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [e for e in events[1:] if e[0] != "task"]


async def _multi_stream(ctx: RunContext) -> Outcome:
    expected = "two SubscribeToTask streams receive the same updates"
    task_id = None
    for text in ctx.probe_texts()[:6]:
        events = await ctx.send(
            text, options=SendOptions(stream=False, return_immediately=True, inherit_ids=False)
        )
        if any(e.kind == "error" and (e.data or {}).get("category") == "auth" for e in events):
            return skipped("the agent requires sign-in; add credentials to check this")
        candidate = next((e.task_id for e in events if e.task_id), None)
        if candidate and await _still_running(ctx, candidate):
            task_id = candidate
            break
    if task_id is None:
        return skipped("every probe task finished (or waited for input) too soon to test")
    first, second = asyncio.Event(), asyncio.Event()
    a = asyncio.create_task(_collect(ctx, task_id, first))
    b: asyncio.Task[list[tuple[str, str]]] | None = None
    try:
        await asyncio.wait_for(first.wait(), 10)
        b = asyncio.create_task(_collect(ctx, task_id, second))
        got_a, got_b = await asyncio.wait_for(asyncio.gather(a, b), SETTLE_S)
    except Exception as exc:
        if "UNSUPPORTED" in str(exc).upper() or "terminal" in str(exc).lower():
            return skipped(f"task {task_id} finished before both streams opened")
        raise
    finally:
        for t in (a, b):
            if t is not None and not t.done():
                t.cancel()
    ups_a, ups_b = _after_task(got_a), _after_task(got_b)
    final_a = got_a[-1][1] if got_a else None
    final_b = got_b[-1][1] if got_b else None
    if final_a in RUNNING:
        return skipped(f"the first stream ended while the task was {final_a}")
    if final_b != final_a or ups_a[len(ups_a) - len(ups_b) :] != ups_b:
        return violated(
            expected,
            f"first: {len(ups_a)} update(s) ending {final_a}; "
            f"second: {len(ups_b)} ending {final_b}",
        )
    return passed(expected, f"both ended {final_a}; second saw the last {len(ups_b)} update(s)")


for check in (
    Check(
        "L1.resilience_resubscribe",
        "L",
        "Resubscribing after a dropped stream returns the Task first",
        "A2A §3.1.6, §3.5.2",
        "must",
        "Answer SubscribeToTask with the current Task, then continue with live updates.",
        _resubscribe,
        applies=_streams,
    ),
    Check(
        "L2.resilience_independent",
        "L",
        "A task keeps running when its stream drops",
        "A2A §3.5.2",
        "must",
        "Do not cancel or fail a task because the client's stream disconnected.",
        _independent,
        applies=_streams,
    ),
    Check(
        "L3.resilience_multi_stream",
        "L",
        "Several streams of one task receive the same updates",
        "A2A §3.5.2",
        "must",
        "Deliver every update of a task to each open stream for it.",
        _multi_stream,
        applies=_streams,
    ),
):
    register(check)
