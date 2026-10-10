"""Checks judged from one recorded exchange, without sending anything (A2A §3.1.2, §3.1.4, §5.4)."""

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel

REASON_CODES: dict[str, tuple[int, int]] = {
    "TASK_NOT_FOUND": (-32001, 404),
    "TASK_NOT_CANCELABLE": (-32002, 400),
    "PUSH_NOTIFICATION_NOT_SUPPORTED": (-32003, 400),
    "UNSUPPORTED_OPERATION": (-32004, 400),
    "CONTENT_TYPE_NOT_SUPPORTED": (-32005, 400),
    "INVALID_AGENT_RESPONSE": (-32006, 500),
    "EXTENDED_AGENT_CARD_NOT_CONFIGURED": (-32007, 400),
    "EXTENSION_SUPPORT_REQUIRED": (-32008, 400),
    "VERSION_NOT_SUPPORTED": (-32009, 400),
}
"""A2A §5.4: the JSON-RPC code and HTTP status of each A2A error, by ErrorInfo reason."""


class PassiveFinding(BaseModel):
    """One rule judged on a recorded exchange."""

    check_id: str
    title: str
    spec_ref: str
    level: str
    status: str  # "pass" | "fail" | "warn"
    expected: str
    actual: str


def _json(text: str | None) -> Any:
    try:
        return json.loads(text or "")
    except ValueError:
        return None


def _jsonrpc(record: dict[str, Any]) -> dict[str, Any] | None:
    body = _json(record.get("request_body"))
    return body if isinstance(body, dict) and "jsonrpc" in body else None


def _frames(record: dict[str, Any], jsonrpc: bool) -> list[dict[str, Any]]:
    out = []
    for frame in record.get("frames") or []:
        data = "\n".join(
            line[5:].strip()
            for line in str(frame.get("data", "")).splitlines()
            if line.startswith("data:")
        )
        parsed = _json(data)
        if isinstance(parsed, dict):
            out.append(parsed.get("result", parsed) if jsonrpc else parsed)
    return out


def _finding(
    check_id: str, title: str, ref: str, ok: bool, expected: str, actual: str
) -> PassiveFinding:
    return PassiveFinding(
        check_id=check_id,
        title=title,
        spec_ref=ref,
        level="must",
        status="pass" if ok else "fail",
        expected=expected,
        actual=actual,
    )


def _stream_first(record: dict[str, Any], rpc: dict[str, Any] | None) -> PassiveFinding | None:
    op = record.get("operation")
    if op not in ("send_message", "subscribe_task") or not record.get("frames"):
        return None
    frames = _frames(record, rpc is not None)
    if not frames or "error" in frames[0]:
        return None
    first = next(iter(frames[0]), "")
    if op == "subscribe_task":
        return _finding(
            "P1.subscribe_task_first",
            "SubscribeToTask sends the Task first",
            "A2A §3.1.6",
            first == "task",
            "first event is the Task",
            f"first event is {first or 'empty'}",
        )
    ok = first == "task" or (first == "message" and len(frames) == 1)
    actual = f"first event is {first or 'empty'}" + (
        f", then {len(frames) - 1} more" if first == "message" and len(frames) > 1 else ""
    )
    return _finding(
        "P1.stream_first_event",
        "A stream begins with the Task (or is one Message)",
        "A2A §3.1.2",
        ok,
        "the Task first, or exactly one Message",
        actual,
    )


def _list_artifacts(record: dict[str, Any], rpc: dict[str, Any] | None) -> PassiveFinding | None:
    if record.get("operation") != "list_tasks" or record.get("status") != 200:
        return None
    if rpc is not None:
        include = bool((rpc.get("params") or {}).get("includeArtifacts"))
    else:
        query = parse_qs(urlparse(str(record.get("url", ""))).query)
        include = (query.get("includeArtifacts") or ["false"])[0].lower() == "true"
    if include:
        return None
    body = _json(record.get("response_body"))
    result = body.get("result", body) if isinstance(body, dict) else None
    if not isinstance(result, dict):
        return None
    with_artifacts = [t.get("id") for t in result.get("tasks") or [] if "artifacts" in t]
    return _finding(
        "P2.list_artifacts_omitted",
        "ListTasks omits artifacts unless asked",
        "A2A §3.1.4",
        not with_artifacts,
        "no artifacts field without includeArtifacts",
        f"artifacts on {len(with_artifacts)} task(s)" if with_artifacts else "omitted",
    )


def _error_code(record: dict[str, Any], rpc: dict[str, Any] | None) -> PassiveFinding | None:
    body = _json(record.get("response_body"))
    if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
        return None
    error = body["error"]
    details = error.get("data") if rpc is not None else error.get("details")
    reason = next(
        (
            d.get("reason")
            for d in details or []
            if isinstance(d, dict) and str(d.get("@type", "")).endswith("ErrorInfo")
        ),
        None,
    )
    if reason not in REASON_CODES:
        return None
    jsonrpc, http = REASON_CODES[reason]
    if rpc is not None:
        want, got = jsonrpc, error.get("code")
    else:
        want, got = http, record.get("status")
    return _finding(
        "P3.error_code",
        "The error uses the binding's code for its reason",
        "A2A §5.4",
        got == want,
        f"{reason} → {want}",
        f"{reason} → {got}",
    )


RULES = (_stream_first, _list_artifacts, _error_code)


def evaluate(record: dict[str, Any]) -> list[PassiveFinding]:
    """Judge the rules that apply to one recorded HTTP exchange (gRPC exchanges yield none)."""
    if not str(record.get("url", "")).startswith("http"):
        return []
    rpc = _jsonrpc(record)
    return [f for rule in RULES if (f := rule(record, rpc)) is not None]
