"""Building the authentication plan for a call to a registered agent."""

from typing import Any, Literal

from a2a.types import AgentCard, SecurityScheme
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel

from a2a_workbench.core.auth.apply import _KIND_FOR, AuthPlan, build_auth_plan
from a2a_workbench.core.auth.requirements import requirement_alternatives
from a2a_workbench.core.auth.store import CredentialInfo, CredentialStore

_TYPE = {
    "api_key_security_scheme": "apiKey",
    "http_auth_security_scheme": "http",
    "oauth2_security_scheme": "oauth2",
    "open_id_connect_security_scheme": "openIdConnect",
    "mtls_security_scheme": "mutualTLS",
}
_REQUIRED_FIELDS = {
    "api_key": ("value",),
    "http_basic": ("username", "password"),
    "http_bearer": ("token",),
    "oauth2": ("access_token",),
    "mtls": ("cert_pem", "key_pem"),
}


class SchemeOverview(BaseModel):
    """One declared security scheme, in plain language, with its stored credential."""

    name: str
    type: str
    label: str
    description: str
    details: dict[str, Any]
    accepts: list[str]
    credential: CredentialInfo | None


class SecurityOverview(BaseModel):
    """How an agent asks to be authenticated and whether we can satisfy it."""

    status: Literal["not_required", "signed_in", "sign_in_needed"]
    schemes: list[SchemeOverview]
    requirements: list[list[str]]
    active: list[str]
    missing: list[str]


def _label(scheme: SecurityScheme) -> str:
    kind = scheme.WhichOneof("scheme")
    if kind == "http_auth_security_scheme":
        return (
            "Username & password"
            if scheme.http_auth_security_scheme.scheme.lower() == "basic"
            else "Bearer token"
        )
    return {
        "api_key_security_scheme": "API key",
        "oauth2_security_scheme": "OAuth 2.0",
        "open_id_connect_security_scheme": "OpenID Connect",
        "mtls_security_scheme": "Client certificate",
    }.get(kind or "", "Unknown scheme")


def _accepts(scheme: SecurityScheme) -> list[str]:
    kind = scheme.WhichOneof("scheme") or ""
    if kind == "http_auth_security_scheme":
        return (
            ["http_basic"]
            if scheme.http_auth_security_scheme.scheme.lower() == "basic"
            else ["http_bearer"]
        )
    return sorted(_KIND_FOR.get(kind, set()))


class CredentialError(ValueError):
    """Raised when a credential does not fit the scheme it is stored for."""


class AuthService:
    """Combines an agent's stored credentials with its card's security requirements."""

    def __init__(self, credentials: CredentialStore) -> None:
        self.credentials = credentials

    async def plan(
        self, agent_id: str, card: AgentCard, *, skill_id: str | None = None
    ) -> AuthPlan:
        """Return the auth plan for calling ``agent_id`` (optionally for one skill)."""
        return build_auth_plan(card, await self.credentials.all(agent_id), skill_id=skill_id)

    async def overview(self, agent_id: str, card: AgentCard) -> SecurityOverview:
        """Describe every declared scheme, the requirement alternatives and our status."""
        infos = {i.scheme_name: i for i in await self.credentials.list(agent_id)}
        schemes = []
        for name, scheme in card.security_schemes.items():
            kind = scheme.WhichOneof("scheme") or ""
            body = MessageToDict(getattr(scheme, kind)) if kind else {}
            schemes.append(
                SchemeOverview(
                    name=name,
                    type=_TYPE.get(kind, "unknown"),
                    label=_label(scheme),
                    description=str(body.pop("description", "")),
                    details=body,
                    accepts=_accepts(scheme),
                    credential=infos.get(name),
                )
            )
        alternatives = requirement_alternatives(card)
        plan = await self.plan(agent_id, card)
        status: Literal["not_required", "signed_in", "sign_in_needed"]
        if not alternatives:
            status = "not_required"
        elif plan.missing or not plan.scheme_names:
            status = "sign_in_needed"
        else:
            status = "signed_in"
        return SecurityOverview(
            status=status,
            schemes=sorted(schemes, key=lambda s: s.name),
            requirements=[sorted(a) for a in alternatives],
            active=sorted(plan.scheme_names),
            missing=plan.missing,
        )

    async def set_credential(
        self, agent_id: str, card: AgentCard, scheme_name: str, kind: str, secret: dict[str, Any]
    ) -> CredentialInfo:
        """Validate and store a credential for one of the card's schemes.

        Raises:
            CredentialError: if the scheme is unknown, the kind does not fit it,
                or required fields are missing.
        """
        if scheme_name not in card.security_schemes:
            raise CredentialError(f"the agent card declares no scheme named '{scheme_name}'")
        if kind not in _accepts(card.security_schemes[scheme_name]):
            raise CredentialError(f"a {kind} credential does not fit scheme '{scheme_name}'")
        missing = [f for f in _REQUIRED_FIELDS[kind] if not secret.get(f)]
        if missing:
            raise CredentialError(f"missing {', '.join(missing)}")
        return await self.credentials.put(agent_id, scheme_name, kind, secret)  # type: ignore[arg-type]
