"""OAuth 2.0 token requests (RFC 6749 / 8628 / 7636 / 8414) through recorded HTTP."""

import base64
import hashlib
import secrets
import time
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from a2a_workbench.core.connection.http import build_http_client
from a2a_workbench.core.connection.recorder import ExchangeSink, recording_scope

SECRET_FIELDS = frozenset(
    {
        "client_secret",
        "password",
        "refresh_token",
        "access_token",
        "id_token",
        "code",
        "code_verifier",
        "device_code",
    }
)
ClientAuthMethod = Literal["client_secret_post", "client_secret_basic"]


class OAuthError(Exception):
    """An OAuth endpoint answered with an error (``error`` is the OAuth error code)."""

    def __init__(self, error: str, description: str = "", status: int | None = None) -> None:
        super().__init__(f"{error}: {description}" if description else error)
        self.error = error
        self.description = description
        self.status = status


class TokenSet(BaseModel):
    """Tokens returned by a token endpoint."""

    access_token: str
    token_type: str = "Bearer"
    expires_at: float | None = None
    refresh_token: str | None = None
    scopes: list[str] = []
    id_token: str | None = None


def _tokens(body: dict[str, Any], requested: list[str]) -> TokenSet:
    expires_in = body.get("expires_in")
    scope = body.get("scope")
    return TokenSet(
        access_token=body["access_token"],
        token_type=body.get("token_type", "Bearer"),
        expires_at=time.time() + float(expires_in) if expires_in else None,
        refresh_token=body.get("refresh_token"),
        scopes=scope.split() if isinstance(scope, str) else list(requested),
        id_token=body.get("id_token"),
    )


async def _post_token(
    token_url: str,
    form: dict[str, str],
    sink: ExchangeSink,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    auth_method: ClientAuthMethod = "client_secret_post",
    operation: str = "oauth_token",
) -> dict[str, Any]:
    headers = {"accept": "application/json"}
    data = dict(form)
    if client_id is not None:
        if auth_method == "client_secret_basic" and client_secret is not None:
            raw = f"{client_id}:{client_secret}".encode()
            headers["authorization"] = "Basic " + base64.b64encode(raw).decode()
        else:
            data["client_id"] = client_id
            if client_secret is not None:
                data["client_secret"] = client_secret
    with recording_scope(operation, redact_fields=SECRET_FIELDS):
        async with build_http_client(sink) as http:
            try:
                response = await http.post(token_url, data=data, headers=headers)
            except httpx.HTTPError as exc:
                raise OAuthError("unreachable", f"could not reach {token_url}: {exc}") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise OAuthError(
            "invalid_response", f"HTTP {response.status_code} without JSON", response.status_code
        ) from exc
    if response.status_code >= 400 or "error" in body:
        if "error" in body:
            raise OAuthError(
                str(body["error"]), str(body.get("error_description", "")), response.status_code
            )
        raise OAuthError(
            "non_standard_error", str(body.get("message") or body)[:500], response.status_code
        )
    if "access_token" not in body:
        raise OAuthError(
            "invalid_response", "no access_token in the response", response.status_code
        )
    return body


async def client_credentials(
    token_url: str,
    client_id: str,
    client_secret: str,
    scopes: list[str],
    sink: ExchangeSink,
    *,
    auth_method: ClientAuthMethod = "client_secret_post",
) -> TokenSet:
    """Run the client credentials grant and return the tokens.

    Raises:
        OAuthError: if the endpoint refuses or cannot be reached.
    """
    form = {"grant_type": "client_credentials"}
    if scopes:
        form["scope"] = " ".join(scopes)
    body = await _post_token(
        token_url,
        form,
        sink,
        client_id=client_id,
        client_secret=client_secret,
        auth_method=auth_method,
    )
    return _tokens(body, scopes)


async def password_grant(
    token_url: str,
    client_id: str,
    client_secret: str | None,
    username: str,
    password: str,
    scopes: list[str],
    sink: ExchangeSink,
    *,
    auth_method: ClientAuthMethod = "client_secret_post",
) -> TokenSet:
    """Run the resource owner password grant and return the tokens."""
    form = {"grant_type": "password", "username": username, "password": password}
    if scopes:
        form["scope"] = " ".join(scopes)
    body = await _post_token(
        token_url,
        form,
        sink,
        client_id=client_id,
        client_secret=client_secret,
        auth_method=auth_method,
    )
    return _tokens(body, scopes)


async def refresh(
    token_url: str,
    refresh_token: str,
    client_id: str,
    client_secret: str | None,
    scopes: list[str],
    sink: ExchangeSink,
    *,
    auth_method: ClientAuthMethod = "client_secret_post",
) -> TokenSet:
    """Exchange a refresh token for new tokens (keeping the refresh token if none is returned)."""
    body = await _post_token(
        token_url,
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
        sink,
        client_id=client_id,
        client_secret=client_secret,
        auth_method=auth_method,
    )
    tokens = _tokens(body, scopes)
    return (
        tokens
        if tokens.refresh_token
        else tokens.model_copy(update={"refresh_token": refresh_token})
    )


def pkce_pair() -> tuple[str, str]:
    """Return a ``(code_verifier, S256 code_challenge)`` pair."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorize_url(
    authorization_url: str,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
    response_type: Literal["code", "token"] = "code",
    code_challenge: str | None = None,
) -> str:
    """Return the URL to send the user's browser to for authorization."""
    params = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    sep = "&" if "?" in authorization_url else "?"
    return f"{authorization_url}{sep}{urlencode(params)}"


async def exchange_code(
    token_url: str,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str | None,
    code_verifier: str | None,
    scopes: list[str],
    sink: ExchangeSink,
    *,
    auth_method: ClientAuthMethod = "client_secret_post",
) -> TokenSet:
    """Exchange an authorization code (with its PKCE verifier) for tokens."""
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    if code_verifier:
        form["code_verifier"] = code_verifier
    body = await _post_token(
        token_url,
        form,
        sink,
        client_id=client_id,
        client_secret=client_secret,
        auth_method=auth_method,
    )
    return _tokens(body, scopes)


async def device_authorize(
    device_url: str, client_id: str, scopes: list[str], sink: ExchangeSink
) -> dict[str, Any]:
    """Start a device authorization; return ``device_code``, ``user_code``, ``verification_uri``…"""
    form = {"client_id": client_id}
    if scopes:
        form["scope"] = " ".join(scopes)
    with recording_scope("oauth_device_authorization", redact_fields=SECRET_FIELDS):
        async with build_http_client(sink) as http:
            try:
                response = await http.post(
                    device_url, data=form, headers={"accept": "application/json"}
                )
            except httpx.HTTPError as exc:
                raise OAuthError("unreachable", f"could not reach {device_url}: {exc}") from exc
    body = response.json()
    if response.status_code >= 400 or "device_code" not in body:
        raise OAuthError(
            str(body.get("error", "http_error")),
            str(body.get("error_description", "")),
            response.status_code,
        )
    return body


async def device_poll(
    token_url: str,
    device_code: str,
    client_id: str,
    client_secret: str | None,
    scopes: list[str],
    sink: ExchangeSink,
) -> TokenSet | None:
    """Poll the token endpoint once; return tokens, or None while authorization is pending.

    Raises:
        OAuthError: for any error other than ``authorization_pending``/``slow_down``.
    """
    try:
        body = await _post_token(
            token_url,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
            },
            sink,
            client_id=client_id,
            client_secret=client_secret,
        )
    except OAuthError as exc:
        if exc.error in ("authorization_pending", "slow_down"):
            return None
        raise
    return _tokens(body, scopes)


async def discover(metadata_url: str, sink: ExchangeSink) -> dict[str, Any]:
    """Fetch an RFC 8414 or OpenID Connect discovery document."""
    with recording_scope("oauth_discovery"):
        async with build_http_client(sink) as http:
            try:
                response = await http.get(metadata_url, headers={"accept": "application/json"})
                response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise OAuthError("discovery_failed", f"{metadata_url}: {exc}") from exc
    if not isinstance(body, dict):
        raise OAuthError("discovery_failed", f"{metadata_url} did not return a JSON object")
    return body
