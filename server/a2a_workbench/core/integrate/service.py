"""Integration guides for registered agents."""

from typing import Any

from pydantic import BaseModel

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.errors import AgentCallError
from a2a_workbench.core.integrate.readiness import Finding, readiness
from a2a_workbench.core.integrate.templates import TARGETS, Snippet, render

GUIDANCE = [
    "Discover the agent from its Agent Card and use only what the card declares (A2A §8). "
    "Skills tell your orchestrator which agent to call; the agent itself picks the skill "
    "for each request, since A2A messages carry no skill.",
    "Send the user's request as-is, only resolving references to earlier turns. Do not add "
    "details the user did not give.",
    "Keep the context_id the agent returns and send it back to continue the conversation; "
    "never invent one (A2A §3.4.1).",
    "When a task is input_required, answer on the same task_id. Answer only from what the "
    "user said; otherwise ask the user (A2A §3.4.3).",
    "Finished tasks cannot be continued: send a follow-up in the same context with "
    "reference_task_ids pointing at the earlier task (A2A Life of a Task).",
    "Treat artifacts as the result and messages as progress or questions (A2A §3.7).",
    "On auth_required, resolve the sign-in or pass it up to your own caller, then continue "
    "the same task; watch the task (subscribe or poll) because the agent may continue on its "
    "own (A2A §7.6.2).",
    "Use streaming when the card declares it; if a stream drops, resubscribe to the task "
    "instead of resending the message (A2A §3.5.2).",
    "A2A leaves presentation to the client. Rewrite mode: your orchestrator answers the user "
    "and the agent's output stays available for inspection. Pass-through mode: the agent's "
    "output and questions go to the user verbatim and are added to the orchestrator's context "
    "as already shown. Either way, pass artifacts (files, data) through as delivered and say "
    "which agent asked a question.",
]


class IntegrationGuide(BaseModel):
    """Code for every target, how to call the agent from another agent, and readiness findings."""

    agent_id: str
    agent: str
    card_url: str
    snippets: dict[str, Snippet]
    guidance: list[str]
    readiness: list[Finding]


class IntegrationService:
    """Builds integration guides from registered agents' cards."""

    def __init__(self, agents: Any) -> None:
        self._agents = agents

    async def guide(self, agent_id: str, *, live: bool = True) -> IntegrationGuide:
        """Return the guide for ``agent_id``.

        With ``live``, a declared extended card is also fetched to report
        ``ExtendedAgentCardNotConfiguredError`` (advice, A2A §3.3.4).

        Raises:
            AgentNotFoundError: if the agent is not registered.
        """
        agent = await self._agents.get(agent_id)
        card = card_from_json(agent.card)
        card_url = agent.base_url.rstrip("/") + (agent.card_path or "/.well-known/agent-card.json")
        findings = readiness(card)
        if live and card.capabilities.extended_agent_card:
            try:
                await self._agents.get_extended_card(agent_id)
            except AgentCallError as exc:
                if exc.classified.get("reason") == "EXTENDED_AGENT_CARD_NOT_CONFIGURED":
                    findings.append(
                        Finding(
                            level="advice",
                            code="extended_card_not_configured",
                            message="The card declares an extended agent card, but the agent "
                            "answers that none is configured. Configure one, or set "
                            "capabilities.extendedAgentCard to false.",
                            path="capabilities.extendedAgentCard",
                            spec_ref="A2A §3.3.4",
                        )
                    )
        return IntegrationGuide(
            agent_id=agent.id,
            agent=agent.name,
            card_url=card_url,
            snippets={t: render(card, card_url, t) for t in TARGETS},
            guidance=GUIDANCE,
            readiness=findings,
        )
