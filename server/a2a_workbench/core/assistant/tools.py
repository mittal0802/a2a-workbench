"""Agent tools derived from Agent Cards, and the A2A rules a tool call must follow.

Each registered agent becomes one tool. Its description uses only Agent Card
fields and its inputs map one-to-one onto ``Message`` and
``SendMessageConfiguration`` fields. A2A messages have no skill field, so there
is no skill input: skills only inform which agent to call and how to phrase
the request.
"""

import re
from typing import Any

from a2a.types import AgentCard
from pydantic import BaseModel

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.assistant.llm import ToolSpec
from a2a_workbench.core.conversations.service import TERMINAL_STATES
from a2a_workbench.core.registry.service import AgentOut

AGENT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "The request as a text part. Pass the user's request as-is, only "
            "resolving references to earlier turns; do not add details.",
        },
        "data": {
            "type": "object",
            "description": "Optional structured data part (only if the agent accepts JSON).",
        },
        "file_urls": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional files to send by URL.",
        },
        "context_id": {
            "type": "string",
            "description": "A context_id this agent returned earlier, to continue that "
            "conversation. Omit to start a new one. Never invent one.",
        },
        "task_id": {
            "type": "string",
            "description": "The task_id of this agent's unfinished task (for example one in "
            "input_required) to continue it. Finished tasks cannot be continued.",
        },
        "reference_task_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Earlier task ids of this agent that a follow-up refers to.",
        },
        "accepted_output_modes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Media types you can use in the reply.",
        },
    },
    "required": ["message"],
}

_TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agent": {"type": "string", "description": "The agent tool name, e.g. call_travel."},
        "task_id": {"type": "string", "description": "A task id that agent returned."},
    },
    "required": ["agent", "task_id"],
}


class AgentTool(BaseModel):
    """A tool offered to the model; ``agent_id`` is None for helper tools."""

    spec: ToolSpec
    agent_id: str | None = None


def _modes(modes: Any) -> str:
    return ", ".join(modes) if modes else "not declared"


def describe_agent(card: AgentCard) -> str:
    """Return a tool description built only from the card's fields."""
    lines = [f"A2A agent: {card.name}.", card.description.strip()]
    lines.append(
        f"Accepts: {_modes(card.default_input_modes)}. "
        f"Replies with: {_modes(card.default_output_modes)}."
    )
    if card.skills:
        lines.append("Skills:")
    for skill in card.skills:
        entry = f"- {skill.name} (id {skill.id}): {skill.description.strip()}"
        if skill.tags:
            entry += f" Tags: {', '.join(skill.tags)}."
        if skill.examples:
            entry += " Examples: " + "; ".join(f'"{e}"' for e in skill.examples) + "."
        if skill.input_modes:
            entry += f" Accepts: {_modes(skill.input_modes)}."
        if skill.output_modes:
            entry += f" Replies with: {_modes(skill.output_modes)}."
        lines.append(entry)
    return "\n".join(line for line in lines if line)


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "agent"
    return f"call_{slug}"[:56]


def build_tools(agents: list[AgentOut]) -> list[AgentTool]:
    """Return one tool per agent (unique ``call_<name>`` names), then the task helpers."""
    tools: list[AgentTool] = []
    used: set[str] = set()
    for agent in agents:
        base = name = _slug(agent.name)
        n = 2
        while name in used:
            name, n = f"{base}_{n}", n + 1
        used.add(name)
        tools.append(
            AgentTool(
                agent_id=agent.id,
                spec=ToolSpec(
                    name=name,
                    description=describe_agent(card_from_json(agent.card)),
                    input_schema=AGENT_INPUT_SCHEMA,
                ),
            )
        )
    tools.append(
        AgentTool(
            spec=ToolSpec(
                name="get_task",
                description="Get a task's current state, messages and artifacts (A2A GetTask).",
                input_schema=_TASK_SCHEMA,
            )
        )
    )
    tools.append(
        AgentTool(
            spec=ToolSpec(
                name="cancel_task",
                description="Ask the agent to cancel an unfinished task (A2A CancelTask).",
                input_schema=_TASK_SCHEMA,
            )
        )
    )
    return tools


class SessionIds:
    """Contexts and tasks each agent returned during a session, with the last known task state."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._contexts: dict[str, set[str]] = {
            a: set(v) for a, v in (data or {}).get("contexts", {}).items()
        }
        self._tasks: dict[str, dict[str, dict[str, str | None]]] = (data or {}).get("tasks", {})

    def record(
        self, agent_id: str, context_id: str | None, task_id: str | None, state: str | None
    ) -> None:
        """Remember ids an agent returned (and the task's latest state)."""
        if context_id:
            self._contexts.setdefault(agent_id, set()).add(context_id)
        if task_id:
            entry = self._tasks.setdefault(agent_id, {}).setdefault(
                task_id, {"context_id": context_id, "state": state}
            )
            entry["context_id"] = context_id or entry.get("context_id")
            entry["state"] = state or entry.get("state")

    def context_known(self, agent_id: str, context_id: str) -> bool:
        """Whether the agent returned ``context_id`` earlier."""
        return context_id in self._contexts.get(agent_id, set())

    def task_state(self, agent_id: str, task_id: str) -> str | None:
        """The task's last known state, or None if the agent never returned it."""
        entry = self._tasks.get(agent_id, {}).get(task_id)
        return entry.get("state") if entry else None

    def task_known(self, agent_id: str, task_id: str) -> bool:
        """Whether the agent returned ``task_id`` earlier."""
        return task_id in self._tasks.get(agent_id, {})

    def context_of(self, agent_id: str, task_id: str) -> str | None:
        """The context the task belongs to, if known."""
        entry = self._tasks.get(agent_id, {}).get(task_id)
        return entry.get("context_id") if entry else None

    def dump(self) -> dict[str, Any]:
        """Return a JSON-serializable copy."""
        return {"contexts": {a: sorted(v) for a, v in self._contexts.items()}, "tasks": self._tasks}


class CallRejected(Exception):
    """A tool call breaks an A2A rule and is not sent; ``rule`` names it, ``spec_ref`` cites it."""

    def __init__(self, rule: str, message: str, spec_ref: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message
        self.spec_ref = spec_ref


def _all_input_modes(card: AgentCard) -> list[str]:
    modes = list(card.default_input_modes)
    for skill in card.skills:
        modes += list(skill.input_modes)
    return [m.lower() for m in modes]


def _accepts_json(modes: list[str]) -> bool:
    return any(m in ("application/json", "data", "*/*") or m.endswith("+json") for m in modes)


def _accepts_files(modes: list[str]) -> bool:
    text_only = {"text", "text/plain", "application/json", "data"}
    return any(m not in text_only and not m.endswith("+json") for m in modes)


def validate_call(card: AgentCard, agent_id: str, args: dict[str, Any], ids: SessionIds) -> None:
    """Check a tool call against A2A's context, task and input-mode rules before sending it.

    Raises:
        CallRejected: naming the broken rule, what to do instead and the spec section.
    """
    context_id, task_id = args.get("context_id"), args.get("task_id")
    if context_id and not ids.context_known(agent_id, context_id):
        raise CallRejected(
            "context_not_issued",
            f"context_id '{context_id}' was never returned by this agent. Omit context_id to "
            "start a new conversation, or use one the agent returned.",
            "A2A §3.4.1 (clients SHOULD NOT provide a client-generated contextId)",
        )
    if task_id:
        if not ids.task_known(agent_id, task_id):
            raise CallRejected(
                "task_unknown",
                f"task_id '{task_id}' was never returned by this agent. Omit task_id to start a "
                "new task.",
                "A2A §3.4.2 (a taskId in a Message MUST reference an existing task)",
            )
        state = ids.task_state(agent_id, task_id)
        if state in TERMINAL_STATES:
            raise CallRejected(
                "task_terminal",
                f"task '{task_id}' is {state} and cannot be continued. Send a follow-up as a new "
                f"task in the same context_id with reference_task_ids: ['{task_id}'].",
                "A2A Life of a Task: Task Immutability and Task Refinements",
            )
        known_context = ids.context_of(agent_id, task_id)
        if context_id and known_context and context_id != known_context:
            raise CallRejected(
                "context_task_mismatch",
                f"task '{task_id}' belongs to context '{known_context}', not '{context_id}'.",
                "A2A §3.4.3 (agents MUST reject mismatching contextId and taskId)",
            )
    for ref in args.get("reference_task_ids") or []:
        if not ids.task_known(agent_id, ref):
            raise CallRejected(
                "reference_unknown",
                f"reference task '{ref}' was never returned by this agent.",
                "A2A §3.4.3 (referenceTaskIds reference related tasks)",
            )
    modes = _all_input_modes(card)
    if modes and args.get("data") is not None and not _accepts_json(modes):
        raise CallRejected(
            "input_mode_not_declared",
            "this agent does not declare a JSON input mode; send the request as text.",
            "A2A AgentCard.defaultInputModes / AgentSkill.inputModes",
        )
    if modes and args.get("file_urls") and not _accepts_files(modes):
        raise CallRejected(
            "input_mode_not_declared",
            "this agent declares only text input modes; it does not accept files.",
            "A2A AgentCard.defaultInputModes / AgentSkill.inputModes",
        )
