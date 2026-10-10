"""Area A — Discovery: the Agent Card (A2A §8)."""

from a2a.types import GetExtendedAgentCardRequest

from a2a_workbench.core.a2a_json import to_json
from a2a_workbench.core.connection.cards import CardFetchError
from a2a_workbench.core.health.checks.common import call, describe, reason_of
from a2a_workbench.core.health.context import RunContext
from a2a_workbench.core.health.model import Check, Outcome, passed, skipped, violated
from a2a_workbench.core.health.registry import register


async def _card_reachable(ctx: RunContext) -> Outcome:
    try:
        preview = await ctx.wb.agents.preview(ctx.agent.base_url, ctx.agent.card_path)
    except CardFetchError as exc:
        return violated("the Agent Card at the well-known path", f"could not load it: {exc}")
    ctx.cache["preview"] = preview
    return passed("the Agent Card", f"served ({len(preview.card)} fields)")


def _missing(fields: dict, names: list[str]) -> list[str]:
    return [n for n in names if not fields.get(n)]


async def _required_fields(ctx: RunContext) -> Outcome:
    card = to_json(ctx.card)
    missing = _missing(
        card,
        [
            "name",
            "description",
            "supportedInterfaces",
            "version",
            "capabilities",
            "defaultInputModes",
            "defaultOutputModes",
            "skills",
        ],
    )
    if "capabilities" in missing and "capabilities" in card:
        missing.remove("capabilities")
    if missing:
        return violated("every REQUIRED AgentCard field", f"missing: {', '.join(missing)}")
    return passed("every REQUIRED AgentCard field", "all present")


async def _interfaces(ctx: RunContext) -> Outcome:
    bad = []
    for i, iface in enumerate(ctx.card.supported_interfaces):
        missing = [
            f for f in ("url", "protocol_binding", "protocol_version") if not getattr(iface, f)
        ]
        if missing:
            bad.append(f"supportedInterfaces[{i}] lacks {', '.join(missing)}")
    if bad:
        return violated(
            "url, protocolBinding and protocolVersion on every interface", "; ".join(bad)
        )
    return passed(
        "url, protocolBinding and protocolVersion on every interface",
        f"{len(ctx.card.supported_interfaces)} interfaces",
    )


async def _skills(ctx: RunContext) -> Outcome:
    bad = []
    for i, skill in enumerate(ctx.card.skills):
        missing = [f for f in ("id", "name", "description", "tags") if not getattr(skill, f)]
        if missing:
            bad.append(f"skills[{i}] ({skill.id or '?'}) lacks {', '.join(missing)}")
    if bad:
        return violated("id, name, description and tags on every skill", "; ".join(bad))
    return passed("id, name, description and tags on every skill", f"{len(ctx.card.skills)} skills")


async def _signature(ctx: RunContext) -> Outcome:
    preview = ctx.cache.get("preview") or await ctx.wb.agents.preview(
        ctx.agent.base_url, ctx.agent.card_path
    )
    if preview.signature_status == "verified":
        return passed("signatures that verify", "verified")
    detail = f"{preview.signature_status}" + (
        f": {preview.signature_detail}" if preview.signature_detail else ""
    )
    return violated("signatures that verify", detail)


async def _caching(ctx: RunContext) -> Outcome:
    preview = ctx.cache.get("preview") or await ctx.wb.agents.preview(
        ctx.agent.base_url, ctx.agent.card_path
    )
    path = ctx.agent.card_path or "/.well-known/agent-card.json"
    record = None
    for eid in preview.exchange_ids:
        candidate = await ctx.wb.exchanges.get(eid)
        if candidate and candidate.get("url", "").split("?")[0].endswith(path):
            record = candidate
    headers = (record or {}).get("response_headers", {})
    cache_control = headers.get("cache-control", "")
    missing = []
    if "max-age" not in cache_control:
        missing.append("Cache-Control with max-age")
    if not headers.get("etag"):
        missing.append("ETag")
    if missing:
        return violated(
            "Cache-Control max-age and ETag on the card", f"missing {', '.join(missing)}"
        )
    return passed("Cache-Control max-age and ETag on the card", f"Cache-Control: {cache_control}")


async def _extended(ctx: RunContext) -> Outcome:
    declared = ctx.capabilities.extended_agent_card
    async with ctx.wb.tasks.client_for(ctx.agent.id, "get_extended_agent_card") as (client, cc):
        _, error = await call(_get_extended(client, cc))
    if declared:
        if error is None:
            return passed(
                "the extended card, or ExtendedAgentCardNotConfiguredError",
                "returned the extended card",
            )
        if reason_of(error) == "EXTENDED_AGENT_CARD_NOT_CONFIGURED":
            return passed(
                "the extended card, or ExtendedAgentCardNotConfiguredError",
                "declared but not configured",
            )
        if error.get("category") == "auth":
            return skipped("the extended card needs sign-in; add credentials to check it")
        return violated(
            "the extended card, or ExtendedAgentCardNotConfiguredError", describe(error)
        )
    if error is not None and reason_of(error) == "UNSUPPORTED_OPERATION":
        return passed("UnsupportedOperationError (not declared)", describe(error))
    actual = "returned an extended card" if error is None else describe(error)
    return violated("UnsupportedOperationError (not declared)", actual)


async def _get_extended(client, cc):  # type: ignore[no-untyped-def]
    from a2a_workbench.core.conversations.errors import classify_error
    from a2a_workbench.core.errors import AgentCallError

    try:
        return await client.get_extended_agent_card(GetExtendedAgentCardRequest(), context=cc)
    except AgentCallError:
        raise
    except Exception as exc:
        raise AgentCallError(classify_error(exc)) from exc


def _unsigned(ctx: RunContext) -> str | None:
    return None if ctx.card.signatures else "the card is not signed"


for check in (
    Check(
        "A1.card_reachable",
        "A",
        "The Agent Card is served",
        "A2A §8.1, §8.2",
        "must",
        "Serve the card at /.well-known/agent-card.json (or the configured card URL).",
        _card_reachable,
        per_interface=False,
    ),
    Check(
        "A2.card_required_fields",
        "A",
        "Required card fields are present",
        "a2a.proto AgentCard (REQUIRED)",
        "must",
        "Fill in name, description, supportedInterfaces, version, capabilities, "
        "defaultInputModes, defaultOutputModes and skills.",
        _required_fields,
        per_interface=False,
    ),
    Check(
        "A3.card_interfaces",
        "A",
        "Every interface declares URL, binding and version",
        "A2A §8.3.1",
        "must",
        "Give each supportedInterfaces entry its url, protocolBinding and protocolVersion.",
        _interfaces,
        per_interface=False,
    ),
    Check(
        "A4.card_skills",
        "A",
        "Every skill has its required fields",
        "a2a.proto AgentSkill (REQUIRED)",
        "must",
        "Give each skill an id, name, description and at least one tag.",
        _skills,
        per_interface=False,
    ),
    Check(
        "A5.card_signature",
        "A",
        "Card signatures verify",
        "A2A §8.4.3",
        "must",
        "Sign the canonical card (RFC 8785) and publish the key at the JWS jku / JWKS.",
        _signature,
        applies=_unsigned,
        per_interface=False,
    ),
    Check(
        "A6.card_caching",
        "A",
        "The card is cacheable",
        "A2A §8.6.1",
        "should",
        "Send Cache-Control with a max-age and an ETag with the card.",
        _caching,
        per_interface=False,
    ),
    Check(
        "A7.extended_capability",
        "A",
        "GetExtendedAgentCard matches the declared capability",
        "A2A §3.3.4",
        "must",
        "Declared: return the extended card or ExtendedAgentCardNotConfiguredError. "
        "Not declared: return UnsupportedOperationError.",
        _extended,
    ),
):
    register(check)
