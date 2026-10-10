"""Area I — Security: the declared authentication is enforced (A2A §3.3.2, §7.4)."""

from a2a_workbench.core.auth.requirements import requirement_alternatives
from a2a_workbench.core.connection.recorder import current_exchange_ids
from a2a_workbench.core.health.context import RunContext
from a2a_workbench.core.health.model import Check, Outcome, passed, skipped, violated
from a2a_workbench.core.health.registry import register


def _requires_auth(ctx: RunContext) -> str | None:
    alternatives = requirement_alternatives(ctx.card)
    if not alternatives:
        return "the card declares no authentication"
    if any(not a for a in alternatives):
        return "the card allows calls without sign-in"
    return None


async def _probe(ctx: RunContext) -> dict[str, object]:
    """Run the enforcement probe; its calls become the current check's evidence."""
    results = await ctx.wb.auth.probe(ctx.agent.id, ctx.card, ctx.interface_url)
    return {r.check: r for r in results}


def _judge(result: object, expected: str) -> Outcome:
    if result is None:
        return skipped("not probed")
    outcome = getattr(result, "outcome", "")
    detail = getattr(result, "detail", "")
    if outcome == "pass":
        return passed(expected, detail)
    if outcome == "fail":
        return violated(expected, detail)
    if outcome == "error":
        raise RuntimeError(detail)
    return skipped(detail)


async def _anonymous(ctx: RunContext) -> Outcome:
    return _judge((await _probe(ctx)).get("rejects_anonymous"), "401/403 without credentials")


async def _wrong(ctx: RunContext) -> Outcome:
    return _judge(
        (await _probe(ctx)).get("rejects_wrong_credentials"), "401/403 for wrong credentials"
    )


async def _challenge(ctx: RunContext) -> Outcome:
    if ctx.binding == "GRPC":
        return skipped("gRPC reports UNAUTHENTICATED without an HTTP challenge header")
    expected = "a WWW-Authenticate header on 401"
    before = set(current_exchange_ids())
    results = await ctx.wb.auth.probe(ctx.agent.id, ctx.card, ctx.interface_url)
    if (
        getattr(next((r for r in results if r.check == "rejects_anonymous"), None), "outcome", "")
        != "pass"
    ):
        return skipped("the agent did not reject the anonymous call")
    for eid in current_exchange_ids():
        if eid in before:
            continue
        record = await ctx.wb.exchanges.get(eid)
        if not record or record.get("status") != 401:
            continue
        headers = {k.lower(): v for k, v in (record.get("response_headers") or {}).items()}
        if headers.get("www-authenticate"):
            return passed(expected, f"WWW-Authenticate: {headers['www-authenticate']}")
        return violated(expected, "401 without WWW-Authenticate")
    return skipped("the agent rejected with 403, not 401")


for check in (
    Check(
        "I1.auth_rejects_anonymous",
        "I",
        "Calls without credentials are rejected",
        "A2A §7.4",
        "must",
        "Authenticate every request against the schemes the card declares.",
        _anonymous,
        applies=_requires_auth,
    ),
    Check(
        "I2.auth_rejects_wrong",
        "I",
        "Calls with wrong credentials are rejected",
        "A2A §7.4",
        "must",
        "Validate the credentials, not just their presence.",
        _wrong,
        applies=_requires_auth,
    ),
    Check(
        "I3.auth_challenge",
        "I",
        "A 401 says how to authenticate",
        "A2A §3.3.2, §7.4",
        "should",
        "Include a WWW-Authenticate header naming the scheme in 401 responses.",
        _challenge,
        applies=_requires_auth,
    ),
):
    register(check)
