"""Exit codes and printers for the CLI."""

import json
import sys
from enum import IntEnum
from typing import Any

from a2a_workbench.core.conversations.timeline import TimelineEvent


class ExitCode(IntEnum):
    """Process exit codes of every command."""

    OK = 0
    CHECKS_FAILED = 1
    USAGE = 2
    CONNECTION = 3
    AUTH = 4
    PROTOCOL = 5
    INTERNAL = 6


_CATEGORY_EXIT = {
    "transport": ExitCode.CONNECTION,
    "auth": ExitCode.AUTH,
    "protocol": ExitCode.PROTOCOL,
    "workbench": ExitCode.INTERNAL,
}


def exit_code_for(category: str) -> ExitCode:
    """Return the exit code for an error category."""
    return _CATEGORY_EXIT.get(category, ExitCode.INTERNAL)


def print_json(value: Any) -> None:
    """Write ``value`` as one line of JSON to stdout."""
    sys.stdout.write(json.dumps(value, default=str) + "\n")
    sys.stdout.flush()


def _texts(parts: list[dict[str, Any]]) -> str:
    out = []
    for p in parts:
        if "text" in p:
            out.append(p["text"])
        elif "data" in p:
            out.append(json.dumps(p["data"]))
        elif "url" in p:
            out.append(f"[file {p.get('filename') or ''} {p['url']}]")
        elif "raw" in p:
            out.append(f"[file {p.get('filename') or ''} {p.get('mediaType') or ''}]")
    return "".join(out)


def describe_event(event: TimelineEvent) -> str | None:
    """Return a one-line human description of a timeline event, or None to skip it.

    Intermediate artifact chunks are skipped; the final chunk prints the
    assembled artifact.
    """
    d = event.data
    if event.kind == "user_message":
        return f"you: {_texts(d['message'].get('parts', []))}"
    if event.kind == "message":
        return f"agent: {_texts(d['message'].get('parts', []))}"
    if event.kind == "task":
        return f"task {event.task_id}: {d['state']}"
    if event.kind == "status":
        message = d.get("status", {}).get("message")
        suffix = f" — {_texts(message.get('parts', []))}" if message else ""
        return f"status: {d['state']}{suffix}"
    if event.kind == "artifact":
        if not d["last_chunk"]:
            return None
        art = d["assembled"]
        name = art.get("name") or art.get("artifactId")
        return f"artifact {name}: {_texts(art.get('parts', []))}"
    if event.kind == "error":
        return f"error ({d['category']}): {d['message']}"
    return None
