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


def _plain_numbers(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _plain_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain_numbers(v) for v in value]
    return value


def _texts(parts: list[dict[str, Any]]) -> str:
    out = []
    for p in parts:
        if "text" in p:
            out.append(p["text"])
        elif "data" in p:
            out.append(json.dumps(_plain_numbers(p["data"])))
        elif "url" in p:
            out.append(f"[file {p.get('filename') or ''} {p['url']}]")
        elif "raw" in p:
            out.append(f"[file {p.get('filename') or ''} {p.get('mediaType') or ''}]")
    return "".join(out)


def _artifact_line(artifact: dict[str, Any]) -> str:
    name = artifact.get("name") or artifact.get("artifactId")
    return f"artifact {name}: {_texts(artifact.get('parts', []))}"


def _status_suffix(status: dict[str, Any]) -> str:
    message = status.get("message")
    return f" — {_texts(message.get('parts', []))}" if message else ""


class HumanPrinter:
    """Turns timeline events into readable lines, printing each artifact once.

    A streamed artifact is printed when its last chunk arrives, or at
    ``finish()`` if the agent never marks one; artifacts inside Task snapshots
    are printed with the task.
    """

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, Any]] = {}
        self._printed: set[str] = set()

    def _emit_artifact(self, artifact: dict[str, Any]) -> list[str]:
        artifact_id = artifact.get("artifactId", "")
        self._pending.pop(artifact_id, None)
        if artifact_id in self._printed:
            return []
        self._printed.add(artifact_id)
        return [_artifact_line(artifact)]

    def feed(self, event: TimelineEvent) -> list[str]:
        """Return the lines describing ``event``."""
        d = event.data
        if event.kind == "artifact":
            if d["last_chunk"]:
                return self._emit_artifact(d["assembled"])
            self._pending[d["assembled"].get("artifactId", "")] = d["assembled"]
            return []
        if event.kind == "task":
            task = d["task"]
            lines = [f"task {event.task_id}: {d['state']}{_status_suffix(task.get('status', {}))}"]
            for artifact in task.get("artifacts", []):
                lines += self._emit_artifact(artifact)
            return lines
        if event.kind == "status":
            return [f"status: {d['state']}{_status_suffix(d.get('status', {}))}"]
        line = describe_event(event)
        return [line] if line else []

    def finish(self) -> list[str]:
        """Return lines for artifacts that never received a last chunk."""
        lines: list[str] = []
        for artifact in list(self._pending.values()):
            lines += self._emit_artifact(artifact)
        return lines


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
