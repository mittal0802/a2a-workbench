"""Small helpers shared by the checks."""

from typing import Any

from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.health.model import NotApplicable, WorkbenchFailure

SIGN_IN = "the agent requires sign-in; add credentials to check this"


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


def guard(error: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return ``error`` when it is the agent's answer; raise when the rule cannot be judged.

    Raises:
        NotApplicable: the agent asked for sign-in, or the SDK offers no such
            call for this interface (``NotImplementedError``).
        WorkbenchFailure: the Workbench itself failed.
    """
    if not error:
        return error
    if error.get("category") == "auth":
        raise NotApplicable(SIGN_IN)
    if error.get("category") == "workbench":
        message = str(error.get("message") or "")
        if "NotImplementedError" in message:
            raise NotApplicable(f"the SDK does not offer this call here: {message}")
        raise WorkbenchFailure(message)
    return error


async def call(coro: Any) -> tuple[Any, dict[str, Any] | None]:
    """Await ``coro``; return ``(value, None)`` or ``(None, the agent's classified error)``.

    Raises:
        NotApplicable, WorkbenchFailure: as ``guard`` decides.
    """
    try:
        return await coro, None
    except AgentCallError as exc:
        return None, guard(exc.classified)
