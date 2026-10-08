"""Agent card resolution and signature verification through the A2A SDK."""

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from a2a.client import A2ACardResolver
from a2a.types import AgentCard, AgentInterface, GetExtendedAgentCardRequest
from a2a.utils.signing import SignatureVerificationError, create_signature_verifier
from jwt import PyJWKSet
from jwt.exceptions import PyJWKError, PyJWTError

from a2a_workbench.core.a2a_json import to_json
from a2a_workbench.core.connection.http import build_http_client
from a2a_workbench.core.connection.recorder import ExchangeSink, recording_scope

SignatureStatus = Literal["verified", "invalid", "unsigned", "unverifiable"]
ALLOWED_JWS_ALGORITHMS = [
    "ES256",
    "ES384",
    "ES512",
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "EdDSA",
]


class CardFetchError(Exception):
    """Raised when an agent card cannot be fetched or parsed."""

    def __init__(self, message: str, cause: BaseException) -> None:
        super().__init__(message)
        self.cause = cause


@dataclass
class CardResult:
    """A resolved agent card with its verification outcome."""

    card: AgentCard
    card_json: dict[str, Any]
    signature_status: SignatureStatus
    signature_detail: str | None = None
    exchange_ids: list[str] = field(default_factory=list)


_LOCAL_PREFIXES = ("localhost", "127.", "0.0.0.0", "[::1]", "::1")


def with_scheme(url: str) -> str:
    """Return ``url`` stripped, prefixed with ``http://`` for local hosts or ``https://``
    for others when it has no scheme."""
    url = url.strip()
    if "://" in url:
        return url
    host = url.split("/", 1)[0].lower()
    local = host.startswith(_LOCAL_PREFIXES) or host.split(":", 1)[0].endswith(".local")
    return ("http://" if local else "https://") + url


def split_card_url(url: str) -> tuple[str, str | None]:
    """Split a user-supplied URL into ``(base_url, card_path)``.

    A URL whose path ends in ``.json`` is treated as the card's own address;
    any other URL is the agent's base URL and the card path is left to the SDK
    default.
    """
    parts = urlsplit(with_scheme(url))
    if parts.path.endswith(".json"):
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        return origin, parts.path + (f"?{parts.query}" if parts.query else "")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")).rstrip("/"), None


def _protected_header(protected: str) -> dict[str, Any]:
    padded = protected + "=" * (-len(protected) % 4)
    header = json.loads(base64.urlsafe_b64decode(padded))
    if not isinstance(header, dict):
        raise ValueError("protected header is not a JSON object")
    return header


async def verify_card_signatures(
    card: AgentCard, http: httpx.AsyncClient
) -> tuple[SignatureStatus, str | None]:
    """Verify ``card.signatures`` with keys from each signature's ``jku`` JWKS URL.

    Returns ``unsigned`` without signatures, ``unverifiable`` when no key can be
    obtained, ``verified`` when at least one signature is valid, else ``invalid``
    with the reason.
    """
    if not card.signatures:
        return "unsigned", None
    keysets: dict[str, PyJWKSet] = {}
    for signature in card.signatures:
        try:
            jku = _protected_header(signature.protected).get("jku")
        except (ValueError, UnicodeDecodeError) as exc:
            return "invalid", f"malformed protected header: {exc}"
        if not jku or jku in keysets:
            continue
        try:
            response = await http.get(jku)
            response.raise_for_status()
            keysets[jku] = PyJWKSet.from_dict(response.json())
        except (httpx.HTTPError, ValueError, PyJWTError) as exc:
            return "unverifiable", f"could not load JWKS from {jku}: {exc}"
    if not keysets:
        return "unverifiable", "no signature names a jku key set URL"

    def key_provider(kid: str | None, jku: str | None) -> Any:
        keyset = keysets.get(jku or "")
        if keyset is None:
            raise PyJWKError(f"no key set loaded for {jku}")
        for key in keyset.keys:
            if kid is None or key.key_id == kid:
                return key
        raise PyJWKError(f"key {kid} not found in {jku}")

    try:
        create_signature_verifier(key_provider, ALLOWED_JWS_ALGORITHMS)(card)
    except SignatureVerificationError as exc:
        return "invalid", str(exc)
    return "verified", None


async def fetch_card(
    url: str,
    sink: ExchangeSink,
    *,
    card_path: str | None = None,
    agent_id: str | None = None,
) -> CardResult:
    """Fetch, parse and verify the agent card addressed by ``url``.

    Raises:
        CardFetchError: if the card cannot be retrieved or parsed.
    """
    base_url, derived_path = split_card_url(url)
    path = card_path or derived_path
    with recording_scope("get_agent_card", agent_id=agent_id) as scope:
        async with build_http_client(sink) as http:
            resolver = A2ACardResolver(http, base_url)
            try:
                card = await resolver.get_agent_card(relative_card_path=path)
            except Exception as exc:
                raise CardFetchError(
                    f"Could not load the agent card from {url.strip()}: {exc}", exc
                ) from exc
            status, detail = await verify_card_signatures(card, http)
    return CardResult(card, to_json(card), status, detail, list(scope.exchange_ids))


async def fetch_extended_card(
    card: AgentCard,
    iface: AgentInterface,
    sink: ExchangeSink,
    *,
    agent_id: str | None = None,
    auth: Any = None,
) -> tuple[AgentCard, list[str]]:
    """Call GetExtendedAgentCard over ``iface`` (authenticated with ``auth``, an
    ``AuthPlan``); return the card and the exchange ids."""
    from a2a_workbench.core.connection.client import open_client
    from a2a_workbench.core.conversations.options import build_call_context

    with recording_scope("get_extended_agent_card", agent_id=agent_id) as scope:
        client = await open_client(card, iface, sink, streaming=False, auth=auth)
        async with client:
            extended = await client.get_extended_agent_card(
                GetExtendedAgentCardRequest(),
                context=build_call_context(None, auth.headers if auth else None),
            )
    return extended, list(scope.exchange_ids)
