"""Checks, their results and the outcome helpers checks return."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from a2a_workbench.core.health.context import RunContext

Area = Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
Status = Literal["pass", "warn", "fail", "not_supported", "error"]
Level = Literal["must", "should"]

AREAS: dict[str, str] = {
    "A": "Discovery",
    "B": "Transports & versions",
    "C": "Messaging",
    "D": "Parts",
    "E": "Task lifecycle",
    "F": "Task operations",
    "G": "Streaming",
    "H": "Push notifications",
    "I": "Security",
    "J": "Extensions",
    "K": "Errors",
    "L": "Resilience",
}


class Outcome(BaseModel):
    """What a check found: ``ok`` (met), ``violated`` (the rule was broken) or ``skipped``."""

    kind: Literal["ok", "violated", "skipped"]
    expected: str = ""
    actual: str = ""


class NotApplicable(Exception):
    """Raised inside a check when the rule cannot be judged here (reported as not_supported)."""


class WorkbenchFailure(Exception):
    """Raised inside a check when the Workbench itself failed (reported as error)."""


def passed(expected: str, actual: str) -> Outcome:
    """The agent met the rule."""
    return Outcome(kind="ok", expected=expected, actual=actual)


def violated(expected: str, actual: str) -> Outcome:
    """The agent broke the rule (fail for MUST, warn for SHOULD)."""
    return Outcome(kind="violated", expected=expected, actual=actual)


def skipped(reason: str) -> Outcome:
    """The rule could not be judged for this agent (counted as not_supported)."""
    return Outcome(kind="skipped", actual=reason)


@dataclass
class Check:
    """One spec requirement and the probe that judges it.

    ``applies`` returns a reason when the check does not apply (the feature is
    not declared, for example); ``per_interface`` checks run once per tested
    interface, the others once per run.
    """

    id: str
    area: Area
    title: str
    spec_ref: str
    level: Level
    fix_hint: str
    run: "Callable[[RunContext], Awaitable[Outcome]]"
    applies: "Callable[[RunContext], str | None]" = field(default=lambda ctx: None)
    per_interface: bool = True


class Result(BaseModel):
    """A check's verdict on one interface, with its evidence."""

    check_id: str
    area: str
    title: str
    spec_ref: str
    level: Level
    interface: str | None
    status: Status
    expected: str = ""
    actual: str = ""
    fix_hint: str = ""
    exchange_ids: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


def status_for(check: Check, outcome: Outcome) -> Status:
    """Map an outcome to a status using the check's level."""
    if outcome.kind == "ok":
        return "pass"
    if outcome.kind == "skipped":
        return "not_supported"
    return "fail" if check.level == "must" else "warn"


def score(counts: dict[str, int]) -> int | None:
    """round(100 × (pass + 0.5 × warn) ÷ (pass + warn + fail)); None when nothing applied."""
    applicable = counts.get("pass", 0) + counts.get("warn", 0) + counts.get("fail", 0)
    if not applicable:
        return None
    return round(100 * (counts.get("pass", 0) + 0.5 * counts.get("warn", 0)) / applicable)


def summarize(results: list[Result]) -> dict[str, Any]:
    """Counts by status, in a fixed key order."""
    counts = {s: 0 for s in ("pass", "warn", "fail", "not_supported", "error")}
    for r in results:
        counts[r.status] += 1
    return counts
