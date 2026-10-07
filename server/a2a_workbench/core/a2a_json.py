"""Conversion between A2A protobuf messages and their canonical JSON form."""

from typing import Any

from a2a.types import AgentCard, TaskState
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.message import Message as ProtoMessage

_STATE_PREFIX = "TASK_STATE_"

TERMINAL_STATES = frozenset({"completed", "failed", "canceled", "rejected"})
INTERRUPTED_STATES = frozenset({"input_required", "auth_required"})


def to_json(message: ProtoMessage) -> dict[str, Any]:
    """Return the canonical A2A JSON (camelCase keys) of a protobuf message."""
    return MessageToDict(message)


def card_from_json(data: dict[str, Any]) -> AgentCard:
    """Parse an ``AgentCard`` from its canonical JSON form, ignoring unknown keys."""
    return ParseDict(data, AgentCard(), ignore_unknown_fields=True)


def state_name(state: int) -> str:
    """Return the lowercase short name of a ``TaskState`` value, e.g. ``input_required``."""
    return TaskState.Name(state).removeprefix(_STATE_PREFIX).lower()
