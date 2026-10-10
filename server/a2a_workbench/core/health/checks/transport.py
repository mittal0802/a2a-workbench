"""Area B — Transports and versions (A2A §3.6, §5.1, §5.2)."""

import uuid

from a2a.types import GetTaskRequest

from a2a_workbench.core.connection.client import interface_override, supported
from a2a_workbench.core.health.checks.common import call, describe, reason_of
from a2a_workbench.core.health.context import RunContext
from a2a_workbench.core.health.model import Check, Outcome, passed, skipped, violated
from a2a_workbench.core.health.registry import register


async def _get_random(ctx: RunContext, version: str | None = None) -> dict | None:
    async def go():  # type: ignore[no-untyped-def]
        async with ctx.wb.tasks.client_for(ctx.agent.id, "get_task") as (client, cc):
            if version is not None:
                from a2a.client import ClientCallContext

                cc = cc or ClientCallContext()
                cc.service_parameters = {**(cc.service_parameters or {}), "A2A-Version": version}
            from a2a_workbench.core.conversations.errors import classify_error
            from a2a_workbench.core.errors import AgentCallError

            try:
                return await client.get_task(
                    GetTaskRequest(id=f"a2aw-health-{uuid.uuid4().hex}"), context=cc
                )
            except AgentCallError:
                raise
            except Exception as exc:
                raise AgentCallError(classify_error(exc)) from exc

    _, error = await call(go())
    return error


async def _answers(ctx: RunContext) -> Outcome:
    error = await _get_random(ctx)
    expected = "TaskNotFoundError for a made-up task (an A2A answer)"
    if reason_of(error) == "TASK_NOT_FOUND" or (error or {}).get("category") == "auth":
        return passed(expected, describe(error))
    return violated(expected, describe(error) if error else "a task for an id that cannot exist")


async def _version(ctx: RunContext) -> Outcome:
    error = await _get_random(ctx, version="99.0")
    if reason_of(error) == "VERSION_NOT_SUPPORTED":
        return passed("VersionNotSupportedError for A2A-Version 99.0", describe(error))
    if error and error.get("category") == "auth":
        return skipped("the agent requires sign-in; add credentials to check this")
    return violated("VersionNotSupportedError for A2A-Version 99.0", describe(error))


async def _equivalent(ctx: RunContext) -> Outcome:
    others = [
        i for i in ctx.card.supported_interfaces if supported(i) and i.url != ctx.interface_url
    ]
    reply = await ctx.reply()
    if reply.kind != "task" or not reply.task_id:
        return skipped("the agent answered with a Message, so there is no task to compare")
    differences = []
    for iface in others:
        token = interface_override.set(iface.url)
        try:
            task, error = await call(ctx.wb.tasks.get(ctx.agent.id, reply.task_id))
        finally:
            interface_override.reset(token)
        if error is not None:
            differences.append(f"{iface.protocol_binding}: {describe(error)}")
        elif task.get("id") != reply.task_id:
            differences.append(f"{iface.protocol_binding}: returned task {task.get('id')}")
    if differences:
        return violated(f"task {reply.task_id} visible on every binding", "; ".join(differences))
    bindings = ", ".join(i.protocol_binding for i in others)
    return passed(f"task {reply.task_id} visible on every binding", f"same task on {bindings}")


def _several(ctx: RunContext) -> str | None:
    usable = [i for i in ctx.card.supported_interfaces if supported(i)]
    return None if len(usable) > 1 else "the card declares a single usable interface"


for check in (
    Check(
        "B1.interface_answers",
        "B",
        "The interface answers A2A calls",
        "A2A §5.2",
        "must",
        "Serve the A2A binding at every URL listed in supportedInterfaces, or remove the entry.",
        _answers,
    ),
    Check(
        "B2.interfaces_equivalent",
        "B",
        "Bindings see the same tasks",
        "A2A §5.1",
        "must",
        "Serve every binding from the same task store and handler.",
        _equivalent,
        applies=_several,
    ),
    Check(
        "B3.version_unsupported",
        "B",
        "Unsupported A2A-Version is refused",
        "A2A §3.6.2",
        "must",
        "Return VersionNotSupportedError when the A2A-Version major version is not served.",
        _version,
    ),
):
    register(check)
