"""Area F — Task operations: GetTask, ListTasks, CancelTask (A2A §3.1.3–§3.1.5, §3.2.4)."""

import json
import uuid
from typing import Any

from a2a_workbench.core.connection.recorder import current_exchange_ids
from a2a_workbench.core.health.checks.common import call, describe, reason_of
from a2a_workbench.core.health.context import TERMINAL_STATES, RunContext
from a2a_workbench.core.health.model import Check, Outcome, passed, skipped, violated
from a2a_workbench.core.health.registry import register
from a2a_workbench.core.tasks.service import ListTasksFilter


async def _task(ctx: RunContext) -> Any:
    """A task the run created (from a probe send), or an Outcome explaining why there is none."""
    reply = await ctx.reply()
    if reply.kind == "error" and (reply.error or {}).get("category") == "auth":
        return skipped("the agent requires sign-in; add credentials to check this")
    if reply.kind != "task" or not reply.task_id:
        return skipped("the agent answered with a Message, so there is no task")
    return reply


async def _get(ctx: RunContext) -> Outcome:
    reply = await _task(ctx)
    if not hasattr(reply, "task_id"):
        return reply
    task, error = await call(ctx.wb.tasks.get(ctx.agent.id, reply.task_id))
    if error is not None:
        return violated(f"task {reply.task_id}", describe(error))
    if task.get("id") != reply.task_id:
        return violated(f"task {reply.task_id}", f"task {task.get('id')}")
    return passed(f"task {reply.task_id}", f"returned, state {task.get('state')}")


async def _get_unknown(ctx: RunContext) -> Outcome:
    made_up = f"a2aw-health-{uuid.uuid4().hex}"
    task, error = await call(ctx.wb.tasks.get(ctx.agent.id, made_up))
    if reason_of(error) == "TASK_NOT_FOUND":
        return passed("TaskNotFoundError", describe(error))
    if error and error.get("category") == "auth":
        return skipped("the agent requires sign-in; add credentials to check this")
    return violated(
        "TaskNotFoundError", describe(error) if error else f"a task ({task.get('state')})"
    )


async def _history(ctx: RunContext) -> Outcome:
    reply = await _task(ctx)
    if not hasattr(reply, "task_id"):
        return reply
    task, error = await call(ctx.wb.tasks.get(ctx.agent.id, reply.task_id, history_length=0))
    if error is not None:
        return violated("no history with historyLength 0", describe(error))
    history = task.get("history") or []
    if history:
        return violated("at most 0 history messages", f"{len(history)} messages")
    return passed("at most 0 history messages", "none")


async def _list_filter(ctx: RunContext) -> Outcome:
    first = await _task(ctx)
    if not hasattr(first, "task_id"):
        return first
    second = await ctx.reply()
    page, error = await call(
        ctx.wb.tasks.list(ctx.agent.id, ListTasksFilter(context_id=first.context_id))
    )
    if error is not None:
        if reason_of(error) == "UNSUPPORTED_OPERATION":
            return skipped("ListTasks is not supported by this agent")
        return violated(f"tasks of context {first.context_id}", describe(error))
    ids = [t.get("id") for t in page["tasks"]]
    others = [t.get("id") for t in page["tasks"] if t.get("contextId") != first.context_id]
    if first.task_id not in ids:
        return violated(f"task {first.task_id} in its context's list", f"{len(ids)} tasks, not it")
    if others or (
        second.task_id and second.context_id != first.context_id and second.task_id in ids
    ):
        return violated(f"only tasks of context {first.context_id}", f"also tasks {others}")
    return passed(
        f"only tasks of context {first.context_id}", f"{len(ids)} task(s), filter honoured"
    )


async def _list_raw(ctx: RunContext) -> tuple[dict[str, Any] | None, str | None]:
    """List tasks and return the raw JSON result from the recorded exchange (None for gRPC)."""
    await _task(ctx)
    before = set(current_exchange_ids())
    _, error = await call(ctx.wb.tasks.list(ctx.agent.id, ListTasksFilter(page_size=50)))
    if error is not None:
        return None, describe(error)
    for eid in current_exchange_ids():
        if eid in before:
            continue
        record = await ctx.wb.exchanges.get(eid)
        if not record or not record.get("response_body"):
            continue
        try:
            body = json.loads(record["response_body"])
        except ValueError:
            continue
        return (body.get("result", body) if isinstance(body, dict) else None), None
    return None, None


def _grpc(ctx: RunContext) -> str | None:
    if ctx.binding == "GRPC":
        return "gRPC carries protobuf, where an empty string or empty list is simply the default"
    return None


async def _next_page_token(ctx: RunContext) -> Outcome:
    result, error = await _list_raw(ctx)
    if error:
        return (
            skipped(f"ListTasks failed: {error}")
            if "UNSUPPORTED" in error
            else violated("a ListTasks response", error)
        )
    if result is None:
        return skipped("no ListTasks response body to inspect")
    if "nextPageToken" not in result:
        return violated(
            'nextPageToken always present ("" on the last page)', "the field is missing"
        )
    return passed(
        'nextPageToken always present ("" on the last page)',
        f'nextPageToken = "{result["nextPageToken"]}"',
    )


async def _artifacts_omitted(ctx: RunContext) -> Outcome:
    result, error = await _list_raw(ctx)
    if error:
        return (
            skipped(f"ListTasks failed: {error}")
            if "UNSUPPORTED" in error
            else violated("a ListTasks response", error)
        )
    if result is None:
        return skipped("no ListTasks response body to inspect")
    leaking = [t.get("id") for t in result.get("tasks", []) if "artifacts" in t]
    if leaking:
        return violated(
            "no artifacts field without includeArtifacts", f"artifacts on {len(leaking)} task(s)"
        )
    return passed("no artifacts field without includeArtifacts", "omitted")


async def _order(ctx: RunContext) -> Outcome:
    await _task(ctx)
    await ctx.reply()
    page, error = await call(ctx.wb.tasks.list(ctx.agent.id, ListTasksFilter(page_size=50)))
    if error is not None:
        if reason_of(error) == "UNSUPPORTED_OPERATION":
            return skipped("ListTasks is not supported by this agent")
        return violated("tasks newest first", describe(error))
    stamps = [((t.get("status") or {}).get("timestamp") or "") for t in page["tasks"]]
    stamped = [s for s in stamps if s]
    if len(stamped) < 2:
        return skipped("fewer than two tasks carry a status timestamp")
    if stamped != sorted(stamped, reverse=True):
        return violated("tasks sorted by status timestamp, newest first", f"order: {stamped[:5]}")
    return passed(
        "tasks sorted by status timestamp, newest first", f"{len(stamped)} tasks in order"
    )


async def _cancel_terminal(ctx: RunContext) -> Outcome:
    reply = await _task(ctx)
    if not hasattr(reply, "task_id"):
        return reply
    if reply.state not in TERMINAL_STATES:
        return skipped("the probe did not leave a finished task")
    if reply.task_id not in ctx.created_tasks:
        return skipped("only tasks this run created are canceled")
    task, error = await call(ctx.wb.tasks.cancel(ctx.agent.id, reply.task_id))
    if reason_of(error) == "TASK_NOT_CANCELABLE":
        return passed("TaskNotCancelableError", describe(error))
    return violated(
        "TaskNotCancelableError",
        describe(error) if error else f"returned the task ({task.get('state')})",
    )


async def _cancel_unknown(ctx: RunContext) -> Outcome:
    made_up = f"a2aw-health-{uuid.uuid4().hex}"
    task, error = await call(ctx.wb.tasks.cancel(ctx.agent.id, made_up))
    if reason_of(error) == "TASK_NOT_FOUND":
        return passed("TaskNotFoundError", describe(error))
    if error and error.get("category") == "auth":
        return skipped("the agent requires sign-in; add credentials to check this")
    return violated(
        "TaskNotFoundError", describe(error) if error else f"a task ({task.get('state')})"
    )


for check in (
    Check(
        "F1.get_task",
        "F",
        "GetTask returns the task",
        "A2A §3.1.3",
        "must",
        "Return the stored task for its id.",
        _get,
    ),
    Check(
        "F2.get_unknown",
        "F",
        "GetTask of an unknown id is TaskNotFoundError",
        "A2A §3.1.3",
        "must",
        "Return TaskNotFoundError for ids that do not exist.",
        _get_unknown,
    ),
    Check(
        "F3.get_history_length",
        "F",
        "GetTask honours historyLength",
        "A2A §3.2.4",
        "must",
        "Never return more history messages than historyLength.",
        _history,
    ),
    Check(
        "F4.list_context_filter",
        "F",
        "ListTasks honours the contextId filter",
        "A2A §3.1.4, §13.1",
        "must",
        "Return only the tasks of the given context.",
        _list_filter,
    ),
    Check(
        "F5.list_next_page_token",
        "F",
        "ListTasks always returns nextPageToken",
        "A2A §3.1.4",
        "must",
        'Always include nextPageToken; send "" on the last page.',
        _next_page_token,
        applies=_grpc,
    ),
    Check(
        "F6.list_artifacts_omitted",
        "F",
        "ListTasks omits artifacts unless asked",
        "A2A §3.1.4",
        "must",
        "Leave the artifacts field out entirely when includeArtifacts is false.",
        _artifacts_omitted,
        applies=_grpc,
    ),
    Check(
        "F7.list_order",
        "F",
        "ListTasks returns the newest tasks first",
        "A2A §3.1.4",
        "must",
        "Sort by status timestamp, most recent first.",
        _order,
    ),
    Check(
        "F8.cancel_terminal",
        "F",
        "Canceling a finished task is TaskNotCancelableError",
        "A2A §3.1.5",
        "must",
        "Return TaskNotCancelableError for completed, failed, canceled or rejected tasks.",
        _cancel_terminal,
    ),
    Check(
        "F9.cancel_unknown",
        "F",
        "Canceling an unknown id is TaskNotFoundError",
        "A2A §3.1.5",
        "must",
        "Return TaskNotFoundError for ids that do not exist.",
        _cancel_unknown,
    ),
):
    register(check)
