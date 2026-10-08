"""A mock OAuth 2.0 / OpenID Connect provider for testing sign-in flows.

Supports client credentials, password, authorization code with PKCE (S256),
implicit, refresh token and device code grants, RFC 8414 and OpenID
discovery documents, and a JWKS. Issued access tokens are RS256 JWTs.
"""

import base64
import hashlib
import json
import secrets
import time
from html import escape
from typing import Any
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from a2a_workbench.fixtures.serve import ThreadServer

IDP_CLIENT = {"id": "workbench-client", "secret": "workbench-secret"}
ALL_GRANTS = [
    "client_credentials",
    "password",
    "authorization_code",
    "implicit",
    "refresh_token",
    "urn:ietf:params:oauth:grant-type:device_code",
]
IDP_USER = {"username": "zoo-user", "password": "zoo-user-pass"}
KID = "idp-1"


class MockIdp:
    """State of the mock provider: signing key, pending codes and device grants."""

    def __init__(
        self,
        issuer: str,
        *,
        token_lifetime: int = 3600,
        grants: list[str] | None = None,
        error_style: str = "oauth",
    ) -> None:
        self.issuer = issuer
        self.token_lifetime = token_lifetime
        self.grants = grants or ALL_GRANTS
        self.error_style = error_style
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
        self.jwk = jwk
        self.codes: dict[str, dict[str, Any]] = {}
        self.devices: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, dict[str, Any]] = {}

    def issue(
        self, client_id: str, scope: str, *, subject: str, openid: bool = False
    ) -> dict[str, Any]:
        """Return a token response for ``client_id`` with ``scope``."""
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "sub": subject,
            "aud": "a2a",
            "iat": now,
            "exp": now + self.token_lifetime,
            "scope": scope,
            "client_id": client_id,
        }
        access = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": KID})
        refresh = secrets.token_urlsafe(24)
        self.refresh_tokens[refresh] = {"client_id": client_id, "scope": scope, "subject": subject}
        body: dict[str, Any] = {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": self.token_lifetime,
            "refresh_token": refresh,
            "scope": scope,
        }
        if openid or "openid" in scope.split():
            body["id_token"] = jwt.encode(
                {
                    "iss": self.issuer,
                    "sub": subject,
                    "aud": client_id,
                    "iat": now,
                    "exp": now + self.token_lifetime,
                    "name": "Zoo User",
                },
                self.key,
                algorithm="RS256",
                headers={"kid": KID},
            )
        return body

    def verify(self, token: str) -> dict[str, Any]:
        """Return the claims of a valid access token; raise ``jwt.PyJWTError`` otherwise."""
        return jwt.decode(
            token, self.key.public_key(), algorithms=["RS256"], audience="a2a", issuer=self.issuer
        )


def _error(error: str, status: int = 400, description: str = "") -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status)


def _client_auth(request: Request, form: dict[str, str]) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            cid, _, csecret = base64.b64decode(header[6:]).decode().partition(":")
        except ValueError:
            return None
    else:
        cid, csecret = form.get("client_id", ""), form.get("client_secret", "")
    if cid == IDP_CLIENT["id"] and secrets.compare_digest(csecret, IDP_CLIENT["secret"]):
        return cid
    return None


def build_idp_app(idp: MockIdp) -> Starlette:
    """Return the ASGI app of the mock provider."""

    def metadata(_: Request) -> JSONResponse:
        i = idp.issuer
        return JSONResponse(
            {
                "issuer": i,
                "authorization_endpoint": f"{i}/authorize",
                "token_endpoint": f"{i}/token",
                "device_authorization_endpoint": f"{i}/device_authorization",
                "jwks_uri": f"{i}/jwks",
                "userinfo_endpoint": f"{i}/userinfo",
                "grant_types_supported": idp.grants,
                "response_types_supported": ["code", "token"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": ["openid", "a2a:invoke", "a2a:extended-card", "booking.write"],
                "token_endpoint_auth_methods_supported": [
                    "client_secret_basic",
                    "client_secret_post",
                ],
                "id_token_signing_alg_values_supported": ["RS256"],
                "subject_types_supported": ["public"],
            }
        )

    def jwks(_: Request) -> JSONResponse:
        return JSONResponse({"keys": [idp.jwk]})

    async def authorize(request: Request) -> Response:
        q = dict(request.query_params)
        if q.get("client_id") != IDP_CLIENT["id"]:
            return HTMLResponse("unknown client", status_code=400)
        fields = "".join(
            f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">' for k, v in q.items()
        )
        return HTMLResponse(
            "<!doctype html><title>Mock IdP sign-in</title><body style='font-family:sans-serif'>"
            f"<h1>Mock IdP</h1><p>Sign in to give <b>{escape(q['client_id'])}</b> access to "
            f"<code>{escape(q.get('scope', ''))}</code>.</p>"
            f"<form method='post' action='/authorize'>{fields}"
            "<button>Approve</button></form></body>"
        )

    async def approve(request: Request) -> Response:
        form = {k: str(v) for k, v in (await request.form()).items()}
        redirect = form["redirect_uri"]
        state = form.get("state", "")
        if form.get("response_type") == "token":
            tokens = idp.issue(
                form["client_id"], form.get("scope", ""), subject=IDP_USER["username"]
            )
            fragment = urlencode(
                {
                    "access_token": tokens["access_token"],
                    "token_type": "Bearer",
                    "expires_in": tokens["expires_in"],
                    "scope": tokens["scope"],
                    "state": state,
                }
            )
            return RedirectResponse(f"{redirect}#{fragment}", status_code=302)
        code = secrets.token_urlsafe(16)
        idp.codes[code] = form
        return RedirectResponse(
            f"{redirect}?{urlencode({'code': code, 'state': state})}", status_code=302
        )

    async def device_authorization(request: Request) -> Response:
        form = {k: str(v) for k, v in (await request.form()).items()}
        if form.get("client_id") != IDP_CLIENT["id"]:
            return _error("invalid_client", 401)
        device_code, user_code = secrets.token_urlsafe(16), secrets.token_hex(3).upper()
        idp.devices[device_code] = {
            "user_code": user_code,
            "scope": form.get("scope", ""),
            "approved": False,
        }
        return JSONResponse(
            {
                "device_code": device_code,
                "user_code": user_code,
                "verification_uri": f"{idp.issuer}/device",
                "verification_uri_complete": f"{idp.issuer}/device?user_code={user_code}",
                "expires_in": 600,
                "interval": 1,
            }
        )

    async def device_page(request: Request) -> Response:
        if request.method == "POST":
            code = str((await request.form()).get("user_code", ""))
            for grant in idp.devices.values():
                if grant["user_code"] == code:
                    grant["approved"] = True
                    return HTMLResponse("<p>Device approved. You can return to the app.</p>")
            return HTMLResponse("<p>Unknown code</p>", status_code=400)
        code = escape(request.query_params.get("user_code", ""))
        return HTMLResponse(
            f"<form method='post'><input name='user_code' value='{code}'>"
            "<button>Approve</button></form>"
        )

    async def token(request: Request) -> Response:
        form = {k: str(v) for k, v in (await request.form()).items()}
        grant = form.get("grant_type")
        if grant not in idp.grants:
            if idp.error_style == "custom":
                allowed = ", ".join(idp.grants)
                return JSONResponse(
                    {
                        "type": "ValidationError",
                        "message": f'"grant_type" must be one of [{allowed}].',
                    },
                    status_code=400,
                )
            return _error("unsupported_grant_type")
        client = _client_auth(request, form)
        if grant == "authorization_code":
            entry = idp.codes.pop(form.get("code", ""), None)
            if entry is None or entry.get("redirect_uri") != form.get("redirect_uri"):
                return _error("invalid_grant", description="unknown code or redirect_uri mismatch")
            challenge = entry.get("code_challenge")
            if challenge:
                verifier = form.get("code_verifier", "")
                digest = (
                    base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                    .rstrip(b"=")
                    .decode()
                )
                if digest != challenge:
                    return _error("invalid_grant", description="PKCE verification failed")
            elif client is None:
                return _error("invalid_client", 401)
            return JSONResponse(
                idp.issue(entry["client_id"], entry.get("scope", ""), subject=IDP_USER["username"])
            )
        if grant == "urn:ietf:params:oauth:grant-type:device_code":
            entry = idp.devices.get(form.get("device_code", ""))
            if entry is None:
                return _error("expired_token")
            if not entry["approved"]:
                return _error("authorization_pending")
            idp.devices.pop(form["device_code"])
            return JSONResponse(
                idp.issue(IDP_CLIENT["id"], entry["scope"], subject=IDP_USER["username"])
            )
        if grant == "refresh_token":
            entry = idp.refresh_tokens.pop(form.get("refresh_token", ""), None)
            if entry is None:
                return _error("invalid_grant", description="unknown refresh token")
            return JSONResponse(
                idp.issue(entry["client_id"], entry["scope"], subject=entry["subject"])
            )
        if client is None:
            return _error("invalid_client", 401, "client authentication failed")
        if grant == "client_credentials":
            return JSONResponse(idp.issue(client, form.get("scope", ""), subject=client))
        if grant == "password":
            if (
                form.get("username") != IDP_USER["username"]
                or form.get("password") != IDP_USER["password"]
            ):
                return _error("invalid_grant", description="wrong username or password")
            return JSONResponse(
                idp.issue(client, form.get("scope", ""), subject=IDP_USER["username"])
            )
        return _error("unsupported_grant_type")

    def userinfo(request: Request) -> Response:
        try:
            claims = idp.verify(request.headers.get("authorization", "")[7:])
        except jwt.PyJWTError:
            return _error("invalid_token", 401)
        return JSONResponse({"sub": claims["sub"], "name": "Zoo User"})

    return Starlette(
        routes=[
            Route("/.well-known/oauth-authorization-server", metadata),
            Route("/.well-known/openid-configuration", metadata),
            Route("/jwks", jwks),
            Route("/authorize", authorize, methods=["GET"]),
            Route("/authorize", approve, methods=["POST"]),
            Route("/device_authorization", device_authorization, methods=["POST"]),
            Route("/device", device_page, methods=["GET", "POST"]),
            Route("/token", token, methods=["POST"]),
            Route("/userinfo", userinfo),
        ]
    )


class IdpServer(ThreadServer):
    """Serves a ``MockIdp`` on a free port; ``.idp`` holds its state."""

    def __init__(
        self,
        *,
        token_lifetime: int = 3600,
        port: int | None = None,
        grants: list[str] | None = None,
        error_style: str = "oauth",
    ) -> None:
        from a2a_workbench.fixtures.runner import free_port

        port = port or free_port()
        self.idp = MockIdp(
            f"http://127.0.0.1:{port}",
            token_lifetime=token_lifetime,
            grants=grants,
            error_style=error_style,
        )
        super().__init__(build_idp_app(self.idp), port=port, ready_path="/jwks")
