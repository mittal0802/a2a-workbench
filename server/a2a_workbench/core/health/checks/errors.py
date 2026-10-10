"""Area K — Errors: A2A errors use each binding's codes and carry a payload (A2A §3.3.2, §5.4)."""

import json
import uuid
from typing import Any

from a2a_workbench.core.connection.recorder import current_exchange_ids
from a2a_workbench.core.health.checks.common import call
from a2a_workbench.core.health.context import TERMINAL_STATES, RunContext
from a2a_workbench.core.health.model import Check, Outcome, passed, skipped, violated
from a2a_workbench.core.health.registry import register

MAPPING: dict[str, tuple[int, str, int]] = {
    "TaskNotFoundError": (-32001, "NOT_FOUND", 404),
    "TaskNotCancelableError": (-32002, "FAILED_PRECONDITION", 400),
}
"""A2A §5.4: JSON-RPC code, gRPC status and HTTP status of the errors the checks provoke."""


async def _provoke(
    ctx: RunContext,
) -> list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]]:
    """Provoke A2A errors; return (error name, classified error, recorded exchange) per probe."""
    return await ctx.cached("error_probes", lambda: _provoke_once(ctx))


async def _provoke_once(
    ctx: RunContext,
) -> list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]]:
    probes: list[tuple[str, Any]] = [
        (
            "TaskNotFoundError",
            lambda: ctx.wb.tasks.get(ctx.agent.id, f"a2aw-health-{uuid.uuid4().hex}"),
        )
    ]
    reply = await ctx.reply()
    if reply.kind == "task" and reply.task_id and reply.state in TERMINAL_STATES:
        task_id = reply.task_id
        probes.append(
            ("TaskNotCancelableError", lambda: ctx.wb.tasks.cancel(ctx.agent.id, task_id))
        )
    out = []
    for name, make in probes:
        before = set(current_exchange_ids())
        _, error = await call(make())
        record = None
        for eid in current_exchange_ids():
            if eid not in before:
                record = await ctx.wb.exchanges.get(eid)
        out.append((name, error, record))
    return out


def _body(record: dict[str, Any] | None) -> Any:
    try:
        return json.loads((record or {}).get("response_body") or "")
    except ValueError:
        return None


async def _mapping(ctx: RunContext) -> Outcome:
    probes = await _provoke(ctx)
    if any((e or {}).get("category") == "auth" for _, e, _ in probes):
        return skipped("the agent requires sign-in; add credentials to check this")
    wrong: list[str] = []
    seen: list[str] = []
    for name, error, record in probes:
        jsonrpc, grpc_status, http = MAPPING[name]
        if error is None:
            wrong.append(f"{name}: the call succeeded")
            continue
        if ctx.binding == "GRPC":
            got = error.get("grpc_status") or (record or {}).get("error") or "?"
            ok = grpc_status in str(got)
            want, actual = grpc_status, str(got)
        elif ctx.binding == "HTTP+JSON":
            want, actual = str(http), str((record or {}).get("status"))
            ok = want == actual
        else:
            got = ((_body(record) or {}).get("error") or {}).get("code")
            want, actual = str(jsonrpc), str(got)
            ok = want == actual
        seen.append(f"{name} → {actual}")
        if not ok:
            wrong.append(f"{name}: {actual} (expected {want})")
    expected = ", ".join(f"{n} → {MAPPING[n]}" for n, _, _ in probes)
    if wrong:
        return violated(expected, "; ".join(wrong))
    return passed(expected, "; ".join(seen))


def _grpc(ctx: RunContext) -> str | None:
    if ctx.binding == "GRPC":
        return "gRPC carries the error as a status; its payload is not recorded"
    return None


async def _payload(ctx: RunContext) -> Outcome:
    probes = await _provoke(ctx)
    if any((e or {}).get("category") == "auth" for _, e, _ in probes):
        return skipped("the agent requires sign-in; add credentials to check this")
    _, error, record = probes[0]
    body = _body(record)
    if error is None or not isinstance(body, dict):
        return skipped("no error response body to inspect")
    if ctx.binding == "HTTP+JSON":
        err = body.get("error") or {}
        expected = "error.code, error.message and an ErrorInfo detail with a reason"
        reasons = [
            d.get("reason")
            for d in err.get("details") or []
            if isinstance(d, dict) and str(d.get("@type", "")).endswith("ErrorInfo")
        ]
        missing = [f for f in ("code", "message") if not err.get(f)]
        if missing or not any(reasons):
            return violated(
                expected, f"missing {', '.join(missing + ([] if any(reasons) else ['ErrorInfo']))}"
            )
        return passed(expected, f"code {err['code']}, reason {reasons[0]}")
    err = body.get("error") or {}
    expected = "error.code (integer) and error.message (string)"
    if not isinstance(err.get("code"), int) or not isinstance(err.get("message"), str):
        return violated(expected, json.dumps(err)[:200])
    return passed(expected, f"code {err['code']}, message {err['message']!r}")


for check in (
    Check(
        "K1.errors_mapping",
        "K",
        "A2A errors use the binding's error codes",
        "A2A §5.4",
        "must",
        "Map each A2A error to the JSON-RPC code, gRPC status and HTTP status in A2A §5.4.",
        _mapping,
    ),
    Check(
        "K2.errors_payload",
        "K",
        "Error responses carry a code and a message",
        "A2A §3.3.2, §5.4",
        "must",
        "Return the error's code and a human-readable message (and ErrorInfo over HTTP+JSON).",
        _payload,
        applies=_grpc,
    ),
):
    register(check)
