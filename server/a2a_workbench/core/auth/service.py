"""Building the authentication plan for a call to a registered agent."""

from a2a.types import AgentCard

from a2a_workbench.core.auth.apply import AuthPlan, build_auth_plan
from a2a_workbench.core.auth.store import CredentialStore


class AuthService:
    """Combines an agent's stored credentials with its card's security requirements."""

    def __init__(self, credentials: CredentialStore) -> None:
        self.credentials = credentials

    async def plan(
        self, agent_id: str, card: AgentCard, *, skill_id: str | None = None
    ) -> AuthPlan:
        """Return the auth plan for calling ``agent_id`` (optionally for one skill)."""
        return build_auth_plan(card, await self.credentials.all(agent_id), skill_id=skill_id)
