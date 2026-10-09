"""Turning stored credentials into what goes on the wire for a call."""

import base64
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, quote_plus

from a2a.types import AgentCard

from a2a_workbench.core.auth.requirements import choose_requirement, requirement_alternatives
from a2a_workbench.core.connection.recorder import REDACTED

_KIND_FOR = {
    "api_key_security_scheme": {"api_key"},
    "http_auth_security_scheme": {"http_basic", "http_bearer", "oauth2"},
    "oauth2_security_scheme": {"oauth2", "http_bearer"},
    "open_id_connect_security_scheme": {"oauth2", "http_bearer"},
    "mtls_security_scheme": {"mtls"},
}


@dataclass
class TlsMaterial:
    """A client certificate, its private key and optionally the CA to trust (PEM)."""

    cert_pem: str
    key_pem: str
    ca_pem: str | None = None


@dataclass
class AuthPlan:
    """Headers, query parameters and TLS material that authenticate a call.

    ``scheme_names`` are the schemes applied; ``missing`` lists schemes of the
    first requirement alternative that lack a usable credential when none of
    the alternatives can be satisfied.
    """

    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    tls: TlsMaterial | None = None
    scheme_names: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def secrets(self) -> set[str]:
        """Return every credential value this plan sends, raw and URL-encoded.

        Covers query values, header values, the token after an ``Authorization``
        scheme word, and each cookie value. Values shorter than four characters
        are left out so that masking does not mangle ordinary text.
        """
        raw: set[str] = set(self.query.values())
        for name, value in self.headers.items():
            raw.add(value)
            if " " in value:
                raw.add(value.split(" ", 1)[1])
            if name.lower() == "cookie":
                for item in value.split(";"):
                    if "=" in item:
                        raw.add(item.split("=", 1)[1].strip())
        out: set[str] = set()
        for value in raw:
            if len(value) >= 4:
                out |= {value, quote(value, safe=""), quote_plus(value, safe="")}
        return out

    def scrub(self, data: Any) -> Any:
        """Return ``data`` with every credential value in its strings masked.

        Walks dicts and lists; non-string leaves are returned unchanged.
        """
        secrets = sorted(self.secrets(), key=len, reverse=True)
        if not secrets:
            return data

        def walk(value: Any) -> Any:
            if isinstance(value, str):
                for secret in secrets:
                    value = value.replace(secret, REDACTED)
                return value
            if isinstance(value, dict):
                return {k: walk(v) for k, v in value.items()}
            if isinstance(value, list | tuple):
                return [walk(v) for v in value]
            return value

        return walk(data)


def _usable(card: AgentCard, credentials: dict[str, dict[str, Any]]) -> set[str]:
    usable = set()
    for name, cred in credentials.items():
        if name not in card.security_schemes:
            continue
        kind = card.security_schemes[name].WhichOneof("scheme")
        if kind and cred.get("kind") in _KIND_FOR.get(kind, set()):
            usable.add(name)
    return usable


def _bearer(cred: dict[str, Any]) -> str:
    return f"Bearer {cred.get('access_token') or cred.get('token', '')}"


def build_auth_plan(
    card: AgentCard, credentials: dict[str, dict[str, Any]], *, skill_id: str | None = None
) -> AuthPlan:
    """Return the plan satisfying the card's (or ``skill_id``'s) security requirements.

    ``credentials`` maps scheme names to stored credentials (each with a
    ``kind``). API keys go to a header, query parameter or cookie as declared;
    HTTP Basic becomes ``Authorization: Basic``; HTTP Bearer, OAuth2 and OpenID
    Connect become ``Authorization: Bearer``; mutual TLS yields ``tls``.
    """
    alternatives = requirement_alternatives(card, skill_id)
    chosen = choose_requirement(alternatives, _usable(card, credentials))
    plan = AuthPlan()
    if chosen is None:
        first = alternatives[0]
        plan.missing = sorted(n for n in first if n not in _usable(card, credentials))
        return plan
    cookies: list[str] = []
    for name in sorted(chosen):
        scheme = card.security_schemes[name]
        cred = credentials[name]
        kind = scheme.WhichOneof("scheme")
        plan.scheme_names.append(name)
        if kind == "api_key_security_scheme":
            spec = scheme.api_key_security_scheme
            location = spec.location.lower()
            if location == "query":
                plan.query[spec.name] = str(cred["value"])
            elif location == "cookie":
                cookies.append(f"{spec.name}={cred['value']}")
            else:
                plan.headers[spec.name] = str(cred["value"])
        elif kind == "http_auth_security_scheme" and cred.get("kind") == "http_basic":
            raw = f"{cred.get('username', '')}:{cred.get('password', '')}".encode()
            plan.headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        elif kind in (
            "http_auth_security_scheme",
            "oauth2_security_scheme",
            "open_id_connect_security_scheme",
        ):
            plan.headers["Authorization"] = _bearer(cred)
        elif kind == "mtls_security_scheme":
            plan.tls = TlsMaterial(cred["cert_pem"], cred["key_pem"], cred.get("ca_pem"))
    if cookies:
        plan.headers["Cookie"] = "; ".join(cookies)
    return plan
