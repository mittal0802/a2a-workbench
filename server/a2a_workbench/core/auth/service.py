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
    """One declared security scheme, in plain language, with its stored credential.

    For OAuth2 / OpenID Connect, ``flows`` lists the declared flows (snake
    case) and ``scopes`` every scope with its description.
    """

    name: str
    type: str
    label: str
    description: str
    details: dict[str, Any]
    accepts: list[str]
    credential: CredentialInfo | None
    flows: list[str] = []
    scopes: dict[str, str] = {}


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


_FLOW_FIELDS = {
    "client_credentials": "client_credentials",
    "authorization_code": "authorization_code",
    "password": "password",
    "device_code": "device_code",
    "implicit": "implicit",
}
REFRESH_MARGIN_S = 30


def oauth_flows(scheme: SecurityScheme) -> dict[str, dict[str, Any]]:
    """Return the scheme's OAuth flows keyed by snake-case name (empty for non-OAuth)."""
    if scheme.WhichOneof("scheme") != "oauth2_security_scheme":
        return {}
    flows = scheme.oauth2_security_scheme.flows
    out = {}
    for name in _FLOW_FIELDS:
        if flows.HasField(name):  # type: ignore[arg-type]
            out[name] = MessageToDict(getattr(flows, name), preserving_proto_field_name=True)
    return out


class AuthService:
    """Combines an agent's stored credentials with its card's security requirements."""

    def __init__(self, credentials: CredentialStore, sink: Any = None) -> None:
        self.credentials = credentials
        self._sink = sink

    async def plan(
        self, agent_id: str, card: AgentCard, *, skill_id: str | None = None
    ) -> AuthPlan:
        """Return the auth plan for calling ``agent_id`` (optionally for one skill).

        OAuth tokens that expire within 30 seconds are renewed first (refresh
        token, or a new client credentials grant); a failed renewal keeps the
        old token so the agent's own answer is shown.
        """
        credentials = await self.credentials.all(agent_id)
        for name, cred in list(credentials.items()):
            if cred.get("kind") == "oauth2" and self._expiring(cred):
                renewed = await self._renew(agent_id, name, cred)
                if renewed is not None:
                    credentials[name] = {"kind": "oauth2", **renewed}
        return build_auth_plan(card, credentials, skill_id=skill_id)

    @staticmethod
    def _expiring(cred: dict[str, Any]) -> bool:
        import time

        expires_at = cred.get("expires_at")
        return bool(expires_at) and float(expires_at) - REFRESH_MARGIN_S <= time.time()

    async def _renew(
        self, agent_id: str, scheme: str, cred: dict[str, Any]
    ) -> dict[str, Any] | None:
        from a2a_workbench.core.auth import oauth

        try:
            if cred.get("refresh_token") and cred.get("token_url"):
                tokens = await oauth.refresh(
                    cred["token_url"],
                    cred["refresh_token"],
                    cred.get("client_id", ""),
                    cred.get("client_secret"),
                    cred.get("scopes", []),
                    self._sink,
                    auth_method=cred.get("auth_method", "client_secret_post"),
                )
            elif cred.get("flow") == "client_credentials" and cred.get("token_url"):
                tokens = await oauth.client_credentials(
                    cred["token_url"],
                    cred["client_id"],
                    cred["client_secret"],
                    cred.get("scopes", []),
                    self._sink,
                    auth_method=cred.get("auth_method", "client_secret_post"),
                )
            else:
                return None
        except oauth.OAuthError:
            return None
        secret = {k: v for k, v in cred.items() if k != "kind"}
        secret.update(tokens.model_dump())
        await self.credentials.put(
            agent_id, scheme, "oauth2", secret, expires_at=_dt(tokens.expires_at)
        )
        return secret

    async def endpoints(self, card: AgentCard, scheme_name: str, flow: str) -> dict[str, str]:
        """Return the flow's endpoints, filling gaps from the scheme's discovery document."""
        from a2a_workbench.core.auth import oauth

        scheme = card.security_schemes[scheme_name]
        found = dict(oauth_flows(scheme).get(flow, {}))
        kind = scheme.WhichOneof("scheme")
        metadata_url = None
        if kind == "oauth2_security_scheme":
            metadata_url = scheme.oauth2_security_scheme.oauth2_metadata_url or None
        elif kind == "open_id_connect_security_scheme":
            metadata_url = scheme.open_id_connect_security_scheme.open_id_connect_url
        needed = {"token_url", "authorization_url", "device_authorization_url"}
        if metadata_url and not needed & {k for k, v in found.items() if v}:
            try:
                meta = await oauth.discover(metadata_url, self._sink)
            except oauth.OAuthError:
                meta = {}
            found.setdefault("token_url", meta.get("token_endpoint", ""))
            found.setdefault("authorization_url", meta.get("authorization_endpoint", ""))
            found.setdefault(
                "device_authorization_url", meta.get("device_authorization_endpoint", "")
            )
        return {k: str(v) for k, v in found.items() if isinstance(v, str) and v}

    async def sign_in(
        self,
        agent_id: str,
        scheme_name: str,
        *,
        flow: str,
        client_id: str,
        client_secret: str | None = None,
        scopes: list[str] | None = None,
        auth_method: str = "client_secret_post",
        username: str | None = None,
        password: str | None = None,
        card: AgentCard | None = None,
    ) -> CredentialInfo:
        """Run a direct OAuth flow (client credentials or password) and store the tokens.

        Raises:
            CredentialError: for an unknown scheme or a flow without a token URL.
            AgentCallError: when the token endpoint refuses (category ``auth``).
        """
        from a2a_workbench.core.auth import oauth
        from a2a_workbench.core.errors import AgentCallError

        if card is None:
            raise CredentialError("the agent card is required")
        if scheme_name not in card.security_schemes:
            raise CredentialError(f"the agent card declares no scheme named '{scheme_name}'")
        endpoints = await self.endpoints(card, scheme_name, flow)
        token_url = endpoints.get("token_url")
        if not token_url:
            raise CredentialError(f"no token URL known for the {flow} flow of '{scheme_name}'")
        requested = list(scopes or [])
        try:
            if flow == "client_credentials":
                if not client_secret:
                    raise CredentialError("client secret is required")
                tokens = await oauth.client_credentials(
                    token_url,
                    client_id,
                    client_secret,
                    requested,
                    self._sink,
                    auth_method=auth_method,  # type: ignore[arg-type]
                )
            elif flow == "password":
                if not username or not password:
                    raise CredentialError("username and password are required")
                tokens = await oauth.password_grant(
                    token_url,
                    client_id,
                    client_secret,
                    username,
                    password,
                    requested,
                    self._sink,
                    auth_method=auth_method,  # type: ignore[arg-type]
                )
            else:
                raise CredentialError(f"{flow} needs a browser or device step")
        except oauth.OAuthError as exc:
            raise AgentCallError(
                {
                    "category": "auth",
                    "message": str(exc),
                    "reason": exc.error,
                    "http_status": exc.status,
                }
            ) from exc
        return await self.store_tokens(
            agent_id,
            scheme_name,
            tokens,
            flow=flow,
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            auth_method=auth_method,
        )

    async def store_tokens(
        self,
        agent_id: str,
        scheme_name: str,
        tokens: Any,
        *,
        flow: str,
        token_url: str | None,
        client_id: str,
        client_secret: str | None,
        auth_method: str,
    ) -> CredentialInfo:
        """Store tokens with what is needed to renew them."""
        secret = {
            "flow": flow,
            "token_url": token_url,
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_method": auth_method,
            **tokens.model_dump(),
        }
        return await self.credentials.put(
            agent_id, scheme_name, "oauth2", secret, expires_at=_dt(tokens.expires_at)
        )

    async def overview(self, agent_id: str, card: AgentCard) -> SecurityOverview:
        """Describe every declared scheme, the requirement alternatives and our status."""
        infos = {i.scheme_name: i for i in await self.credentials.list(agent_id)}
        schemes = []
        for name, scheme in card.security_schemes.items():
            kind = scheme.WhichOneof("scheme") or ""
            body = MessageToDict(getattr(scheme, kind)) if kind else {}
            flows = oauth_flows(scheme)
            scopes: dict[str, str] = {}
            for f in flows.values():
                scopes.update(f.get("scopes", {}))
            schemes.append(
                SchemeOverview(
                    flows=sorted(flows),
                    scopes=scopes,
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


def _dt(epoch: float | None) -> Any:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch, UTC) if epoch else None
