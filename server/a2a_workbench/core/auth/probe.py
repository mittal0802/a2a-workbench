"""Checking that an agent enforces the authentication its card declares."""

import uuid
from typing import Any, Literal

from a2a.types import AgentCard, GetTaskRequest
from pydantic import BaseModel

from a2a_workbench.core.auth.apply import AuthPlan, build_auth_plan
from a2a_workbench.core.auth.requirements import requirement_alternatives

Outcome = Literal["pass", "fail", "warn", "skipped", "not_applicable", "error"]
_WRONG = {
    "api_key": {"kind": "api_key", "value": "a2aw-probe-wrong-key"},
    "http_basic": {"kind": "http_basic", "username": "a2aw-probe", "password": "wrong"},
    "http_bearer": {"kind": "http_bearer", "token": "a2aw-probe-wrong-token"},
    "oauth2": {"kind": "oauth2", "access_token": "a2aw-probe-wrong-token"},
}


class ProbeResult(BaseModel):
    """The outcome of one enforcement check."""

    check: str
    title: str
    outcome: Outcome
    detail: str
    spec_ref: str = "A2A §4 Authentication"


async def _attempt(
    card: AgentCard, iface_url: str | None, sink: Any, plan: AuthPlan, label: str
) -> str:
    """Call GetTask on a random id; return ``accepted``, ``rejected`` or ``error: …``."""
    from a2a_workbench.core.connection.client import open_client, select_interface
    from a2a_workbench.core.connection.recorder import recording_scope
    from a2a_workbench.core.conversations.errors import classify_error
    from a2a_workbench.core.conversations.options import build_call_context

    with recording_scope(f"auth_probe:{label}"):
        try:
            iface = select_interface(card, iface_url)
            client = await open_client(card, iface, sink, streaming=False, auth=plan)
            async with client:
                await client.get_task(
                    GetTaskRequest(id=f"a2aw-probe-{uuid.uuid4().hex}"),
                    context=build_call_context(None, plan.headers),
                )
        except Exception as exc:
            category = classify_error(exc)["category"]
            if category == "auth":
                return "rejected"
            if category == "protocol":
                return "accepted"
            return f"error: {exc}"
    return "accepted"


async def probe_enforcement(
    card: AgentCard,
    credentials: dict[str, dict[str, Any]],
    sink: Any,
    *,
    interface_url: str | None = None,
) -> list[ProbeResult]:
    """Check that the agent rejects anonymous and wrong credentials and accepts ours.

    Each check is a GetTask call for a random task id: an authentication error
    means the call was rejected, any other A2A answer (normally "task not
    found") means it was accepted.
    """
    alternatives = requirement_alternatives(card)
    if not alternatives:
        return [
            ProbeResult(
                check="not_required",
                title="The card declares no authentication",
                outcome="not_applicable",
                detail="Nothing to enforce.",
            )
        ]
    results: list[ProbeResult] = []
    anonymous = await _attempt(card, interface_url, sink, AuthPlan(), "anonymous")
    results.append(
        ProbeResult(
            check="rejects_anonymous",
            title="Blocks requests without sign-in",
            outcome="pass"
            if anonymous == "rejected"
            else "fail"
            if anonymous == "accepted"
            else "error",
            detail={
                "rejected": "Answered 401/403 without credentials.",
                "accepted": "The agent accepted a call without credentials although its card "
                "requires authentication.",
            }.get(anonymous, anonymous),
        )
    )
    first = alternatives[0]
    wrong: dict[str, dict[str, Any]] = {}
    for name in first:
        scheme = card.security_schemes.get(name)
        kind = scheme.WhichOneof("scheme") if scheme else None
        if kind == "api_key_security_scheme":
            wrong[name] = _WRONG["api_key"]
        elif kind == "http_auth_security_scheme":
            basic = scheme.http_auth_security_scheme.scheme.lower() == "basic"  # type: ignore[union-attr]
            wrong[name] = _WRONG["http_basic" if basic else "http_bearer"]
        elif kind in ("oauth2_security_scheme", "open_id_connect_security_scheme"):
            wrong[name] = _WRONG["oauth2"]
    if len(wrong) == len(first):
        outcome_wrong = await _attempt(
            card, interface_url, sink, build_auth_plan(card, wrong), "wrong_credentials"
        )
        results.append(
            ProbeResult(
                check="rejects_wrong_credentials",
                title="Blocks wrong credentials",
                outcome="pass"
                if outcome_wrong == "rejected"
                else "fail"
                if outcome_wrong == "accepted"
                else "error",
                detail={
                    "rejected": "Answered 401/403 to made-up credentials.",
                    "accepted": "The agent accepted made-up credentials.",
                }.get(outcome_wrong, outcome_wrong),
            )
        )
    else:
        results.append(
            ProbeResult(
                check="rejects_wrong_credentials",
                title="Blocks wrong credentials",
                outcome="skipped",
                detail="Wrong client certificates are not probed.",
            )
        )
    plan = build_auth_plan(card, credentials)
    if not plan.scheme_names:
        results.append(
            ProbeResult(
                check="accepts_your_credentials",
                title="Accepts your sign-in",
                outcome="skipped",
                detail="Sign in first to check this.",
            )
        )
    else:
        mine = await _attempt(card, interface_url, sink, plan, "your_credentials")
        results.append(
            ProbeResult(
                check="accepts_your_credentials",
                title="Accepts your sign-in",
                outcome="pass" if mine == "accepted" else "fail" if mine == "rejected" else "error",
                detail={
                    "accepted": "Your credentials were accepted.",
                    "rejected": "The agent rejected your saved credentials.",
                }.get(mine, mine),
            )
        )
    return results
