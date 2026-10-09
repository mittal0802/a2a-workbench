"""Authentication for zoo agents: declared security schemes and their enforcement."""

import base64
import hmac
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import grpc
from a2a.types import (
    APIKeySecurityScheme,
    AuthorizationCodeOAuthFlow,
    ClientCredentialsOAuthFlow,
    DeviceCodeOAuthFlow,
    HTTPAuthSecurityScheme,
    ImplicitOAuthFlow,
    MutualTlsSecurityScheme,
    OAuth2SecurityScheme,
    OAuthFlows,
    OpenIdConnectSecurityScheme,
    PasswordOAuthFlow,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from starlette.types import ASGIApp, Receive, Scope, Send

ZooAuth = Literal[
    "none",
    "apikey-header",
    "apikey-custom",
    "apikey-query",
    "apikey-cookie",
    "basic",
    "bearer",
    "and",
    "mtls",
    "oauth",
    "oidc",
]
ZOO_SECRETS = {
    "api_key": "zoo-api-key-1234",
    "username": "zoo",
    "password": "zoo-pass",
    "token": "zoo-token-5678",
}
PROTECTED_PREFIXES = ("/a2a", "/v1")

Check = Callable[[dict[str, str], dict[str, str], dict[str, str]], bool]


def _eq(a: str | None, b: str) -> bool:
    return a is not None and hmac.compare_digest(a.encode(), b.encode())


def _bearer_ok(headers: dict[str, str]) -> bool:
    return _eq(headers.get("authorization"), f"Bearer {ZOO_SECRETS['token']}")


def _basic_ok(headers: dict[str, str]) -> bool:
    raw = f"{ZOO_SECRETS['username']}:{ZOO_SECRETS['password']}".encode()
    return _eq(headers.get("authorization"), "Basic " + base64.b64encode(raw).decode())


def _key_header_ok(headers: dict[str, str]) -> bool:
    return _eq(headers.get("x-api-key"), ZOO_SECRETS["api_key"])


def _cookies(headers: dict[str, str]) -> dict[str, str]:
    out = {}
    for item in headers.get("cookie", "").split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip()] = v.strip()
    return out


CHECKS: dict[str, Check] = {
    "apikey-header": lambda h, q, c: _key_header_ok(h),
    "apikey-custom": lambda h, q, c: _eq(
        h.get("ocp-apim-subscription-key"), ZOO_SECRETS["api_key"]
    ),
    "apikey-query": lambda h, q, c: _eq(q.get("api_key"), ZOO_SECRETS["api_key"]),
    "apikey-cookie": lambda h, q, c: _eq(c.get("zoo_session"), ZOO_SECRETS["api_key"]),
    "basic": lambda h, q, c: _basic_ok(h),
    "bearer": lambda h, q, c: _bearer_ok(h),
    "and": lambda h, q, c: _key_header_ok(h) and _bearer_ok(h),
    "mtls": lambda h, q, c: True,
}


OAUTH_SCOPES = {
    "a2a:invoke": "Invoke A2A methods",
    "a2a:extended-card": "Fetch the extended agent card",
    "booking.write": "Hold bookings",
}


def oauth_schemes(issuer: str) -> dict[str, SecurityScheme]:
    """Return one OAuth2 scheme per flow of the mock provider at ``issuer``.

    A2A's ``OAuthFlows`` holds exactly one flow, so each flow is its own scheme.
    """
    meta = f"{issuer}/.well-known/oauth-authorization-server"
    token, authz = f"{issuer}/token", f"{issuer}/authorize"

    def scheme(description: str, flows: OAuthFlows) -> SecurityScheme:
        return SecurityScheme(
            oauth2_security_scheme=OAuth2SecurityScheme(
                description=description, flows=flows, oauth2_metadata_url=meta
            )
        )

    return {
        "oauth": scheme(
            "Machine sign-in with a client id and secret.",
            OAuthFlows(
                client_credentials=ClientCredentialsOAuthFlow(token_url=token, scopes=OAUTH_SCOPES)
            ),
        ),
        "oauthCode": scheme(
            "Sign in through the mock provider's page.",
            OAuthFlows(
                authorization_code=AuthorizationCodeOAuthFlow(
                    authorization_url=authz,
                    token_url=token,
                    scopes=OAUTH_SCOPES,
                    pkce_required=True,
                )
            ),
        ),
        "oauthDevice": scheme(
            "Sign in on another device with a code.",
            OAuthFlows(
                device_code=DeviceCodeOAuthFlow(
                    device_authorization_url=f"{issuer}/device_authorization",
                    token_url=token,
                    scopes=OAUTH_SCOPES,
                )
            ),
        ),
        "oauthPassword": scheme(
            "Username and password (deprecated flow).",
            OAuthFlows(password=PasswordOAuthFlow(token_url=token, scopes=OAUTH_SCOPES)),
        ),
        "oauthImplicit": scheme(
            "Browser sign-in returning the token directly (deprecated flow).",
            OAuthFlows(implicit=ImplicitOAuthFlow(authorization_url=authz, scopes=OAUTH_SCOPES)),
        ),
    }


def oauth_check(idp: Any) -> Check:
    """Return a check accepting Bearer JWTs from ``idp`` that carry scope ``a2a:invoke``."""

    def check(headers: dict[str, str], query: dict[str, str], cookies: dict[str, str]) -> bool:
        auth = headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return False
        try:
            claims = idp.verify(auth[7:])
        except Exception:
            return False
        return "a2a:invoke" in str(claims.get("scope", "")).split()

    return check


def security_for(
    mode: str, issuer: str | None = None
) -> tuple[dict[str, SecurityScheme], list[SecurityRequirement]]:
    """Return the security schemes and requirements a zoo agent in ``mode`` declares.

    ``issuer`` is the mock identity provider's URL for ``oauth``.
    """
    if mode == "none":
        return {}, []
    if mode == "oidc":
        if not issuer:
            raise ValueError("oidc mode needs an identity provider")
        scheme = SecurityScheme(
            open_id_connect_security_scheme=OpenIdConnectSecurityScheme(
                description="Sign in with the mock OpenID provider.",
                open_id_connect_url=f"{issuer}/.well-known/openid-configuration",
            )
        )
        requirement = SecurityRequirement(
            schemes={"oidc": StringList(list=["openid", "a2a:invoke"])}
        )
        return {"oidc": scheme}, [requirement]
    if mode == "oauth":
        if not issuer:
            raise ValueError("oauth mode needs an identity provider")
        schemes = oauth_schemes(issuer)
        requirements = [
            SecurityRequirement(schemes={name: StringList(list=["a2a:invoke"])}) for name in schemes
        ]
        return schemes, requirements
    schemes = {
        "apiKey": SecurityScheme(
            api_key_security_scheme=APIKeySecurityScheme(location="header", name="X-API-Key")
        ),
        "apiKeyCustom": SecurityScheme(
            api_key_security_scheme=APIKeySecurityScheme(
                location="header", name="Ocp-Apim-Subscription-Key"
            )
        ),
        "apiKeyQuery": SecurityScheme(
            api_key_security_scheme=APIKeySecurityScheme(location="query", name="api_key")
        ),
        "apiKeyCookie": SecurityScheme(
            api_key_security_scheme=APIKeySecurityScheme(location="cookie", name="zoo_session")
        ),
        "basic": SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="Basic")),
        "bearer": SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                scheme="Bearer", bearer_format="opaque"
            )
        ),
        "mtls": SecurityScheme(mtls_security_scheme=MutualTlsSecurityScheme()),
    }
    used = {
        "apikey-header": ["apiKey"],
        "apikey-custom": ["apiKeyCustom"],
        "apikey-query": ["apiKeyQuery"],
        "apikey-cookie": ["apiKeyCookie"],
        "basic": ["basic"],
        "bearer": ["bearer"],
        "and": ["apiKey", "bearer"],
        "mtls": ["mtls"],
    }[mode]
    requirement = SecurityRequirement(schemes={name: StringList() for name in used})
    return {name: schemes[name] for name in used}, [requirement]


def _query(raw: bytes) -> dict[str, str]:
    from urllib.parse import parse_qsl

    return dict(parse_qsl(raw.decode(), keep_blank_values=True))


class ZooAuthMiddleware:
    """Answers 401 to requests on the A2A endpoints that lack the mode's credentials."""

    def __init__(self, app: ASGIApp, mode: str, idp: Any = None) -> None:
        self.app = app
        self.check = oauth_check(idp) if mode in ("oauth", "oidc") else CHECKS.get(mode)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or self.check is None
            or not scope["path"].startswith(PROTECTED_PREFIXES)
        ):
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        if self.check(headers, _query(scope.get("query_string", b"")), _cookies(headers)):
            await self.app(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="zoo"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b'{"error": "unauthenticated"}'})


class ZooGrpcAuthInterceptor(grpc.aio.ServerInterceptor):
    """Rejects gRPC calls whose metadata lacks the mode's credentials."""

    def __init__(self, mode: str, idp: Any = None) -> None:
        self.check = oauth_check(idp) if mode in ("oauth", "oidc") else CHECKS.get(mode)

    async def intercept_service(
        self,
        continuation: Callable[[Any], Awaitable[Any]],
        handler_call_details: Any,
    ) -> Any:
        """Pass authenticated calls on; answer the rest with UNAUTHENTICATED."""
        handler = await continuation(handler_call_details)
        metadata = {k.lower(): v for k, v in handler_call_details.invocation_metadata or ()}
        if self.check is None or self.check(metadata, {}, _cookies(metadata)):
            return handler

        async def deny(request: Any, context: grpc.aio.ServicerContext) -> Any:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "unauthenticated")

        if handler.unary_unary:
            return grpc.unary_unary_rpc_method_handler(
                deny, handler.request_deserializer, handler.response_serializer
            )

        async def deny_stream(request: Any, context: grpc.aio.ServicerContext) -> Any:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "unauthenticated")
            yield  # pragma: no cover

        return grpc.unary_stream_rpc_method_handler(
            deny_stream, handler.request_deserializer, handler.response_serializer
        )
