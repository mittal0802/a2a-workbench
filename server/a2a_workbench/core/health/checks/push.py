"""Area H — Push notifications: config operations and deliveries (A2A §3.1.7–§3.1.10, §4.3)."""

import asyncio
import uuid
from typing import Any

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.health.checks.common import call, describe, reason_of
from a2a_workbench.core.health.context import RunContext
from a2a_workbench.core.health.model import Check, Outcome, passed, skipped, violated
from a2a_workbench.core.health.registry import register

DELIVERY_WAIT_S = 10.0
PROBE_URL = "https://push-probe.invalid/a2a-workbench"
"""Webhook URL for config round trips; nothing is delivered to it."""


def _declared(ctx: RunContext) -> str | None:
    return None if ctx.capabilities.push_notifications else "the card does not declare push"


def _undeclared(ctx: RunContext) -> str | None:
    return "the card declares push notifications" if ctx.capabilities.push_notifications else None


async def _task_id(ctx: RunContext) -> str | Outcome:
    """A task the run created, or an Outcome explaining why there is none."""
    reply = await ctx.reply()
    if reply.kind == "error" and (reply.error or {}).get("category") == "auth":
        return skipped("the agent requires sign-in; add credentials to check this")
    if reply.kind != "task" or not reply.task_id:
        return skipped("the agent answered with a Message, so there is no task")
    return reply.task_id


async def _capability(ctx: RunContext) -> Outcome:
    task_id = await _task_id(ctx)
    if isinstance(task_id, Outcome):
        return task_id
    expected = "PushNotificationNotSupportedError"
    config, error = await call(ctx.wb.push.create(ctx.agent.id, task_id, url=PROBE_URL))
    if reason_of(error) == "PUSH_NOTIFICATION_NOT_SUPPORTED":
        return passed(expected, describe(error))
    return violated(expected, describe(error) if error else f"config {config.get('id')} created")


async def _crud(ctx: RunContext) -> Outcome:
    task_id = await _task_id(ctx)
    if isinstance(task_id, Outcome):
        return task_id
    expected = "create, get, list and delete the config"
    config_id = f"a2aw-health-{uuid.uuid4().hex[:12]}"
    created, error = await call(
        ctx.wb.push.create(ctx.agent.id, task_id, url=PROBE_URL, config_id=config_id)
    )
    if error is not None:
        return violated(expected, f"create: {describe(error)}")
    config_id = created.get("id") or config_id
    if created.get("url") != PROBE_URL:
        return violated(expected, f"create returned url {created.get('url')!r}")
    got, error = await call(ctx.wb.push.get(ctx.agent.id, task_id, config_id))
    if error is not None:
        return violated(expected, f"get: {describe(error)}")
    if got.get("id") != config_id or got.get("url") != PROBE_URL:
        return violated(expected, f"get returned {got.get('id')} {got.get('url')!r}")
    listed, error = await call(ctx.wb.push.list(ctx.agent.id, task_id))
    if error is not None:
        return violated(expected, f"list: {describe(error)}")
    if config_id not in {c.get("id") for c in listed["configs"]}:
        return violated(expected, f"list did not include config {config_id}")
    _, error = await call(ctx.wb.push.delete(ctx.agent.id, task_id, config_id))
    if error is not None:
        return violated(expected, f"delete: {describe(error)}")
    listed, error = await call(ctx.wb.push.list(ctx.agent.id, task_id))
    if error is None and config_id in {c.get("id") for c in listed["configs"]}:
        return violated(expected, f"config {config_id} still listed after delete")
    return passed(expected, f"config {config_id} round trip succeeded")


async def _delete_idempotent(ctx: RunContext) -> Outcome:
    task_id = await _task_id(ctx)
    if isinstance(task_id, Outcome):
        return task_id
    expected = "a second delete succeeds like the first"
    config_id = f"a2aw-health-{uuid.uuid4().hex[:12]}"
    created, error = await call(
        ctx.wb.push.create(ctx.agent.id, task_id, url=PROBE_URL, config_id=config_id)
    )
    if error is not None:
        return skipped(f"could not create a config: {describe(error)}")
    config_id = created.get("id") or config_id
    _, error = await call(ctx.wb.push.delete(ctx.agent.id, task_id, config_id))
    if error is not None:
        return violated(expected, f"first delete: {describe(error)}")
    _, error = await call(ctx.wb.push.delete(ctx.agent.id, task_id, config_id))
    if error is not None:
        return violated(expected, f"second delete: {describe(error)}")
    return passed(expected, "both deletes succeeded")


async def _delivery_auth(ctx: RunContext) -> Outcome:
    """Send with an inline Workbench webhook and judge the deliveries it receives."""
    expected = "notifications carry the config's Authorization"
    conv = await ctx.new_conversation()
    reply_events = await ctx.send(
        ctx.probe_texts()[0],
        options=SendOptions(stream=False, inherit_ids=False, push=True),
        conversation_id=conv,
    )
    task_id = next((e.task_id for e in reply_events if e.task_id), None)
    if task_id is None:
        return skipped("the agent answered without a task, so no notification is due")
    hook = next(
        (h for h in await ctx.wb.hooks.list(ctx.agent.id) if h.conversation_id == conv), None
    )
    if hook is None:
        return skipped("no Workbench webhook was created for the probe")
    deliveries: list[Any] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DELIVERY_WAIT_S
    while loop.time() < deadline:
        deliveries = [
            d for d in await ctx.wb.receiver.deliveries(ctx.agent.id) if d.hook_id == hook.id
        ]
        if deliveries:
            break
        await asyncio.sleep(0.2)
    if not deliveries:
        base, _ = await ctx.wb.public_url()
        return skipped(
            f"no notification reached {base} within {DELIVERY_WAIT_S:.0f}s; the agent must be "
            "able to reach this Workbench (set a public URL or start a tunnel)"
        )
    bad = [d for d in deliveries if "unauthenticated" in d.reasons]
    if bad:
        return violated(expected, f"{len(bad)} of {len(deliveries)} without valid Authorization")
    return passed(expected, f"{len(deliveries)} notification(s) authenticated")


for check in (
    Check(
        "H1.push_capability",
        "H",
        "Undeclared push notifications are refused",
        "A2A §3.3.4",
        "must",
        "Return PushNotificationNotSupportedError for config calls when push is not declared.",
        _capability,
        applies=_undeclared,
        per_interface=False,
    ),
    Check(
        "H2.push_crud",
        "H",
        "Push configs can be created, read, listed and deleted",
        "A2A §3.1.7–§3.1.10",
        "must",
        "Store the config as sent and return it from Get and List until it is deleted.",
        _crud,
        applies=_declared,
    ),
    Check(
        "H3.push_delete_idempotent",
        "H",
        "Deleting a push config is idempotent",
        "A2A §3.1.10",
        "must",
        "Deleting an already deleted config must succeed with the same effect.",
        _delete_idempotent,
        applies=_declared,
    ),
    Check(
        "H4.push_delivery_auth",
        "H",
        "Notifications carry the configured credentials",
        "A2A §4.3.3",
        "must",
        "Send the config's authentication as the Authorization header of every notification.",
        _delivery_auth,
        applies=_declared,
        per_interface=False,
    ),
):
    register(check)
