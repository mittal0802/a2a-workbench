"""Small helpers shared by the checks."""

from typing import Any

from a2a_workbench.core.errors import AgentCallError


def reason_of(error: dict[str, Any] | None) -> str:
    """The A2A error reason (for example ``TASK_NOT_FOUND``), or ``""``."""
    return str((error or {}).get("reason") or "").upper()


def describe(error: dict[str, Any] | None) -> str:
    """A one-line description of a classified error."""
    if not error:
        return "no error"
    parts = [reason_of(error) or error.get("category", "error")]
    for key in ("code", "http_status", "grpc_status"):
        if error.get(key) is not None:
            parts.append(f"{key}={error[key]}")
    return " · ".join(parts) + (f": {error['message']}" if error.get("message") else "")


async def call(coro: Any) -> tuple[Any, dict[str, Any] | None]:
    """Await ``coro``; return ``(value, None)`` or ``(None, classified error)``."""
    try:
        return await coro, None
    except AgentCallError as exc:
        return None, exc.classified
