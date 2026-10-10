"""Area J — Extensions: required extensions are enforced (A2A §3.3.4)."""

from a2a_workbench.core.health.checks.common import describe, reason_of
from a2a_workbench.core.health.context import RunContext
from a2a_workbench.core.health.model import Check, Outcome, passed, skipped, violated
from a2a_workbench.core.health.registry import register


def _required(ctx: RunContext) -> str | None:
    if any(e.required for e in ctx.capabilities.extensions):
        return None
    return "the card declares no required extension"


async def _enforced(ctx: RunContext) -> Outcome:
    uris = ", ".join(e.uri for e in ctx.capabilities.extensions if e.required)
    expected = f"ExtensionSupportRequiredError when {uris} is not activated"
    reply = await ctx.reply()
    if reply.kind == "error" and (reply.error or {}).get("category") == "auth":
        return skipped("the agent requires sign-in; add credentials to check this")
    if reason_of(reply.error) == "EXTENSION_SUPPORT_REQUIRED":
        return passed(expected, describe(reply.error))
    actual = describe(reply.error) if reply.error else f"answered with a {reply.kind}"
    return violated(expected, actual)


register(
    Check(
        "J1.extension_required",
        "J",
        "Required extensions are enforced",
        "A2A §3.3.4",
        "must",
        "Refuse requests that do not activate a required extension with "
        "ExtensionSupportRequiredError.",
        _enforced,
        applies=_required,
    )
)
