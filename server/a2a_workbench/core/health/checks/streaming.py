"""Area G — Streaming: SendStreamingMessage and SubscribeToTask (A2A §3.1.2, §3.1.6, §3.3.4)."""

import asyncio
import time
import uuid
from typing import Any

from a2a.client import ClientCallContext
from a2a.types import AgentCard, Message, Part, Role

from a2a_workbench.core.connection.client import open_client, select_interface
from a2a_workbench.core.conversations.errors import classify_error
from a2a_workbench.core.conversations.options import SendOptions, build_request
from a2a_workbench.core.health.checks.common import call, describe, guard, reason_of
from a2a_workbench.core.health.context import TERMINAL_STATES, RunContext
from a2a_workbench.core.health.model import Check, Outcome, passed, skipped, violated
from a2a_workbench.core.health.registry import register

CLOSE_WINDOW_S = 5.0
FIRST_EVENT_S = 10.0
STREAM = SendOptions(stream=True, inherit_ids=False)


def _streams(ctx: RunContext) -> str | None:
    return None if ctx.capabilities.streaming else "the card does not declare streaming"


def _no_stream(ctx: RunContext) -> str | None:
    return "the card declares streaming" if ctx.capabilities.streaming else None


async def _undeclared(ctx: RunContext) -> Outcome:
    """Call SendStreamingMessage although streaming is not declared."""
    forced = AgentCard()
    forced.CopyFrom(ctx.card)
    forced.capabilities.streaming = True
    plan = await ctx.wb.auth.plan(ctx.agent.id, ctx.card)
    iface = select_interface(ctx.card, ctx.interface_url)
    client = await open_client(forced, iface, ctx.wb.exchanges, streaming=True, auth=plan)
    message = Message(
        message_id=uuid.uuid4().hex, role=Role.ROLE_USER, parts=[Part(text=ctx.probe_texts()[0])]
    )
    error = None
    events = 0
    try:
        async with client:
            async for _ in client.send_message(
                build_request(message, STREAM),
                context=ClientCallContext(service_parameters=plan.headers),
            ):
                events += 1
    except Exception as exc:
        error = guard(classify_error(exc))
    if reason_of(error) == "UNSUPPORTED_OPERATION":
        return passed("UnsupportedOperationError for SendStreamingMessage", describe(error))
    actual = describe(error) if error else f"streamed {events} event(s)"
    return violated("UnsupportedOperationError for SendStreamingMessage", actual)


async def _stream_events(ctx: RunContext) -> tuple[list[Any], float | None, bool]:
    """Stream the probe; return (agent events, seconds open after a terminal state, closed)."""
    conv = await ctx.new_conversation()
    events: list[Any] = []
    terminal_at: float | None = None
    stream = ctx.wb.conversations.send(conv, [_text(ctx)], STREAM)
    closed = True
    try:
        while True:
            budget = CLOSE_WINDOW_S if terminal_at is not None else 60.0
            try:
                event = await asyncio.wait_for(anext(stream), budget)
            except StopAsyncIteration:
                break
            except TimeoutError:
                closed = False
                break
            if event.kind == "user_message":
                continue
            events.append(event)
            if event.task_id and event.task_id not in ctx.created_tasks:
                ctx.created_tasks.append(event.task_id)
            if event.data.get("state") in TERMINAL_STATES and terminal_at is None:
                terminal_at = time.monotonic()
    finally:
        await stream.aclose()
    held = None if terminal_at is None else time.monotonic() - terminal_at
    return events, held, closed


def _text(ctx: RunContext) -> Any:
    from a2a_workbench.core.conversations.parts import TextPartInput

    return TextPartInput(text=ctx.probe_texts()[0])


async def _first_event(ctx: RunContext) -> Outcome:
    events, _, _ = await _stream_events(ctx)
    if not events:
        return violated("a Task or exactly one Message first", "no events")
    first = events[0]
    if first.kind == "error" and first.data.get("category") == "auth":
        return skipped("the agent requires sign-in; add credentials to check this")
    if first.kind == "task":
        return passed("the stream begins with the Task", "Task first")
    if first.kind == "message":
        if len(events) == 1:
            return passed("exactly one Message", "one Message")
        return violated(
            "a Message-only stream to contain exactly one Message", f"{len(events)} events"
        )
    return violated("the stream to begin with a Task or a Message", f"began with {first.kind}")


async def _closes(ctx: RunContext) -> Outcome:
    events, held, closed = await _stream_events(ctx)
    if events and events[0].kind == "message":
        return skipped("the agent replied with a Message")
    if held is None:
        return skipped("the probe task did not reach a terminal state")
    if not closed:
        return violated(
            f"the stream to close after the terminal state (within {CLOSE_WINDOW_S:g} s)",
            "still open",
        )
    return passed("the stream to close after the terminal state", f"closed {held:.1f} s later")


async def _subscribe_first(ctx: RunContext) -> Outcome:
    target = await ctx.open_task()
    if target is None:
        return skipped("no probe left a task open to subscribe to")
    stream = ctx.wb.tasks.subscribe(ctx.agent.id, target.task_id)
    try:
        first, error = await call(asyncio.wait_for(anext(stream), FIRST_EVENT_S))
    except TimeoutError:
        return violated("the Task as the first event", f"no event within {FIRST_EVENT_S:g} s")
    finally:
        await stream.aclose()
    if error is not None:
        return violated("the Task as the first event", describe(error))
    if first["kind"] == "task":
        return passed("the Task as the first event", f"Task ({first['state']})")
    return violated("the Task as the first event", f"a {first['kind']} event first")


async def _subscribe_terminal(ctx: RunContext) -> Outcome:
    reply = await ctx.reply()
    if reply.kind != "task" or reply.state not in TERMINAL_STATES:
        return skipped("the probe did not leave a finished task")
    events = []

    async def drain() -> None:
        async for e in ctx.wb.tasks.subscribe(ctx.agent.id, reply.task_id):
            events.append(e)

    try:
        _, error = await call(asyncio.wait_for(drain(), FIRST_EVENT_S))
    except TimeoutError:
        error = None
    if reason_of(error) == "UNSUPPORTED_OPERATION":
        return passed("UnsupportedOperationError for a finished task", describe(error))
    actual = describe(error) if error else f"streamed {len(events)} event(s)"
    return violated("UnsupportedOperationError for a finished task", actual)


for check in (
    Check(
        "G1.stream_capability",
        "G",
        "Undeclared streaming is refused",
        "A2A §3.3.4",
        "must",
        "Return UnsupportedOperationError for SendStreamingMessage when streaming is not declared.",
        _undeclared,
        applies=_no_stream,
    ),
    Check(
        "G2.stream_first_event",
        "G",
        "A stream begins with the Task (or is one Message)",
        "A2A §3.1.2",
        "must",
        "Send the Task first, then status and artifact updates; or exactly one Message.",
        _first_event,
        applies=_streams,
    ),
    Check(
        "G3.stream_closes",
        "G",
        "A stream closes when the task finishes",
        "A2A §3.1.2",
        "must",
        "Close the stream once the task reaches a terminal state.",
        _closes,
        applies=_streams,
    ),
    Check(
        "G4.subscribe_task_first",
        "G",
        "SubscribeToTask sends the Task first",
        "A2A §3.1.6",
        "must",
        "Send the current Task as the first event of a subscription.",
        _subscribe_first,
        applies=_streams,
    ),
    Check(
        "G5.subscribe_terminal",
        "G",
        "Subscribing to a finished task is refused",
        "A2A §3.1.6",
        "must",
        "Return UnsupportedOperationError when the task is already terminal.",
        _subscribe_terminal,
        applies=_streams,
    ),
):
    register(check)
