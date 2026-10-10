"""Areas C and E — Messaging and the task lifecycle (A2A §3.1.1, §3.2, §3.4, §3.7)."""

import uuid

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.health.checks.common import describe, reason_of
from a2a_workbench.core.health.context import INTERRUPTED_STATES, TERMINAL_STATES, RunContext
from a2a_workbench.core.health.model import Check, Outcome, passed, skipped, violated
from a2a_workbench.core.health.registry import register

EXACT = SendOptions(stream=False, inherit_ids=False)


def _auth_skip(reply) -> Outcome | None:  # type: ignore[no-untyped-def]
    if reply.kind == "error" and (reply.error or {}).get("category") == "auth":
        return skipped("the agent requires sign-in; add credentials to check this")
    return None


async def _shape(ctx: RunContext) -> Outcome:
    reply = await ctx.reply()
    if (s := _auth_skip(reply)) is not None:
        return s
    if reply.kind in ("task", "message"):
        return passed("a Task or a Message", f"a {reply.kind}")
    return violated("a Task or a Message", describe(reply.error) if reply.error else "nothing")


async def _blocking(ctx: RunContext) -> Outcome:
    reply = await ctx.reply()
    if (s := _auth_skip(reply)) is not None:
        return s
    if reply.kind == "message":
        return passed("a terminal or interrupted state", "replied with a Message")
    if reply.state in TERMINAL_STATES | INTERRUPTED_STATES:
        return passed("a terminal or interrupted state", reply.state or "")
    return violated("a terminal or interrupted state from a blocking send", f"state {reply.state}")


async def _context(ctx: RunContext) -> Outcome:
    reply = await ctx.reply()
    if (s := _auth_skip(reply)) is not None:
        return s
    if reply.context_id:
        return passed("a contextId in the response", reply.context_id)
    return violated("a contextId in the response", f"a {reply.kind} without contextId")


async def _unknown_task(ctx: RunContext) -> Outcome:
    made_up = f"a2aw-health-{uuid.uuid4().hex}"
    reply = await ctx.reply(options=EXACT.model_copy(update={"task_id": made_up}))
    if (s := _auth_skip(reply)) is not None:
        return s
    if reason_of(reply.error) == "TASK_NOT_FOUND":
        return passed(f"TaskNotFoundError for task {made_up}", describe(reply.error))
    actual = (
        describe(reply.error)
        if reply.error
        else f"accepted it ({reply.kind}, task {reply.task_id})"
    )
    return violated(f"TaskNotFoundError for task {made_up}", actual)


async def _mismatch(ctx: RunContext) -> Outcome:
    target = await ctx.open_task() or await ctx.reply()
    if (s := _auth_skip(target)) is not None:
        return s
    if target.kind == "error":
        return skipped(f"the probe message failed: {describe(target.error)}")
    if target.kind != "task" or not target.task_id:
        return skipped("the agent answered with a Message, so there is no task to address")
    other = f"a2aw-health-{uuid.uuid4().hex}"
    reply = await ctx.reply(
        "B", options=EXACT.model_copy(update={"task_id": target.task_id, "context_id": other})
    )
    if reply.kind == "error":
        return passed("the mismatching contextId and taskId rejected", describe(reply.error))
    return violated(
        "the mismatching contextId and taskId rejected",
        f"accepted (task {reply.task_id}, state {reply.state})",
    )


async def _terminal(ctx: RunContext) -> Outcome:
    first = await ctx.reply()
    if (s := _auth_skip(first)) is not None:
        return s
    if first.kind != "task" or first.state not in TERMINAL_STATES:
        return skipped("the probe did not leave a finished task")
    reply = await ctx.reply(
        "more",
        options=EXACT.model_copy(update={"task_id": first.task_id, "context_id": first.context_id}),
    )
    if reason_of(reply.error) == "UNSUPPORTED_OPERATION":
        return passed(
            "UnsupportedOperationError for a message to a finished task", describe(reply.error)
        )
    actual = (
        describe(reply.error)
        if reply.error
        else f"accepted it (task {reply.task_id}, {reply.state})"
    )
    return violated("UnsupportedOperationError for a message to a finished task", actual)


async def _history_zero(ctx: RunContext) -> Outcome:
    reply = await ctx.reply(options=EXACT.model_copy(update={"history_length": 0}))
    if (s := _auth_skip(reply)) is not None:
        return s
    if reply.kind != "task" or reply.task is None:
        return skipped("the agent answered without a Task object")
    history = reply.task.get("history") or []
    if not history:
        return passed("no history with historyLength 0", "history omitted")
    return violated("no history with historyLength 0", f"{len(history)} history messages")


async def _artifacts(ctx: RunContext) -> Outcome:
    reply = await ctx.reply()
    if (s := _auth_skip(reply)) is not None:
        return s
    if reply.kind != "task" or reply.state != "completed":
        return skipped("the probe did not complete a task")
    if reply.artifacts:
        return passed("results as artifacts", f"{reply.artifacts} artifact(s)")
    if reply.messages:
        return violated("results as artifacts", "completed with its output only in messages")
    return passed("results as artifacts", "completed without output")


for check in (
    Check(
        "C1.send_shape",
        "C",
        "SendMessage returns a Task or a Message",
        "A2A §3.1.1",
        "must",
        "Return a Task (for tracked work) or a Message.",
        _shape,
    ),
    Check(
        "C2.send_blocking_state",
        "C",
        "A blocking send waits for a final or interrupted state",
        "A2A §3.2.2",
        "must",
        "Without returnImmediately, return only when the task is terminal or needs input/auth.",
        _blocking,
    ),
    Check(
        "C3.context_generated",
        "C",
        "The response carries the contextId",
        "A2A §3.4.1",
        "must",
        "Include the generated contextId in the Task or Message you return.",
        _context,
    ),
    Check(
        "C4.unknown_task",
        "C",
        "Unknown taskId is refused",
        "A2A §3.4.2",
        "must",
        "Return TaskNotFoundError when a message names a task that does not exist.",
        _unknown_task,
    ),
    Check(
        "C5.context_task_mismatch",
        "C",
        "Mismatching contextId and taskId are refused",
        "A2A §3.4.3",
        "must",
        "Reject a message whose contextId differs from its task's context.",
        _mismatch,
    ),
    Check(
        "C6.terminal_task_message",
        "C",
        "A finished task accepts no new message",
        "A2A §3.1.1",
        "must",
        "Return UnsupportedOperationError for messages to completed, failed, canceled "
        "or rejected tasks.",
        _terminal,
    ),
    Check(
        "C7.history_zero",
        "C",
        "historyLength 0 omits history",
        "A2A §3.2.4",
        "should",
        "Omit Task.history when historyLength is 0.",
        _history_zero,
    ),
    Check(
        "E1.results_as_artifacts",
        "E",
        "Results are returned as artifacts",
        "A2A §3.7",
        "should",
        "Return task output as artifacts; use messages for progress and questions.",
        _artifacts,
    ),
):
    register(check)
