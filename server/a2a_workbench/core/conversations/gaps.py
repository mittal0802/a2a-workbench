"""Comparing what a client saw before a lost connection with what recovery returned."""

import json
from typing import Any, Literal

from a2a_workbench.core.a2a_json import TERMINAL_STATES
from a2a_workbench.core.conversations.timeline import TimelineEvent


def _state(event: TimelineEvent) -> str | None:
    if event.kind in ("task", "status"):
        return event.data.get("state")
    if event.kind == "connection_lost":
        return event.data.get("last_state")
    return None


def _signature(event: TimelineEvent) -> str | None:
    if event.kind == "status":
        return json.dumps(
            ["status", event.data.get("state"), event.data.get("status", {}).get("message")],
            sort_keys=True,
        )
    if event.kind == "artifact":
        art = event.data.get("artifact", {})
        return json.dumps(
            [
                "artifact",
                art.get("artifactId"),
                art.get("parts"),
                event.data.get("append"),
                event.data.get("last_chunk"),
            ],
            sort_keys=True,
        )
    return None


def _artifact_ids(event: TimelineEvent) -> list[str]:
    if event.kind == "artifact":
        return [event.data.get("artifact", {}).get("artifactId", "")]
    if event.kind == "task":
        return [a.get("artifactId", "") for a in event.data.get("task", {}).get("artifacts", [])]
    return []


def analyze_recovery(
    before: list[TimelineEvent],
    after: list[TimelineEvent],
    method: Literal["subscribe", "get_task"],
) -> dict[str, Any]:
    """Summarize a recovery: ordering, states and artifacts missed, and duplicates.

    ``before`` are the task's events seen before recovery and ``after`` the
    events recovery produced. The result has ``method``, ``first_event``,
    ``snapshot_first`` (the first recovered event is a Task), ``state_before``,
    ``state_after``, ``missed_states``, ``missed_artifacts`` (ids not seen
    before, in order), ``duplicate_events`` (status or artifact events
    identical to ones seen before) and ``terminal``.
    """
    seen_states = [s for s in map(_state, before) if s]
    state_before = seen_states[-1] if seen_states else None
    after_states = [s for s in map(_state, after) if s]
    state_after = after_states[-1] if after_states else state_before

    missed_states: list[str] = []
    for s in after_states:
        if s not in seen_states and s not in missed_states:
            missed_states.append(s)

    seen_signatures = {sig for sig in map(_signature, before) if sig}
    duplicates = sum(1 for e in after if (sig := _signature(e)) and sig in seen_signatures)

    seen_ids = {i for e in before for i in _artifact_ids(e)}
    missed_artifacts: list[str] = []
    for e in after:
        for i in _artifact_ids(e):
            if i not in seen_ids and i not in missed_artifacts:
                missed_artifacts.append(i)

    first = after[0].kind if after else None
    return {
        "method": method,
        "first_event": first,
        "snapshot_first": first == "task",
        "state_before": state_before,
        "state_after": state_after,
        "missed_states": missed_states,
        "missed_artifacts": missed_artifacts,
        "duplicate_events": duplicates,
        "terminal": state_after in TERMINAL_STATES,
    }
