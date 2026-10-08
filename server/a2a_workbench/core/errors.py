"""Errors raised by core operations that call an agent."""

from typing import Any


class AgentCallError(Exception):
    """An agent call failed; ``classified`` holds the result of ``classify_error``."""

    def __init__(self, classified: dict[str, Any]) -> None:
        super().__init__(classified.get("message", "agent call failed"))
        self.classified = classified
