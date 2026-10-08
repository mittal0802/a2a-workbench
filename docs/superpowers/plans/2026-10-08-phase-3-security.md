# Phase 3 — Security: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect to agents protected by every security scheme the A2A spec allows (API key in header/query/cookie, HTTP Basic/Bearer, OAuth2 with all five flows, OpenID Connect, mutual TLS), store credentials safely, apply them correctly (including AND/OR security requirements at card and skill level), resume `auth_required` tasks, and show whether the agent actually enforces what it declares.

**Architecture:** A credential **vault** (AES-GCM, key from `A2AW_SECRET_KEY` or an auto-generated 0600 keyfile) stores one credential per (agent, scheme). A **requirement evaluator** picks the first card or skill `SecurityRequirement` whose schemes all have credentials. An **auth applier** turns those credentials into `ClientCallContext.service_parameters` (headers / gRPC metadata, the SDK's own mechanism) and, where the SDK has no mechanism, into transport configuration we already own: query parameters on the httpx client, and the TLS client certificate on httpx and the gRPC channel. **OAuth flows** run in core with an httpx client (recorded like all traffic) against the agent's declared endpoints; the browser-based flows (authorization code + PKCE, implicit) use a backend callback page. Tests use a **mock identity provider** and **auth-* zoo agents** built on the SDK server with Starlette authentication.

**Spec:** `docs/superpowers/specs/2026-10-07-a2a-workbench-design.md` (§3 row I, §5.3, §12 Phase 3)

## Global Constraints

- Phase 1–2 constraints apply. Credentials are never logged, never returned by the API in clear (only masked previews), redacted in recordings (headers already; query keys via `redact_url`; cookies via header redaction).
- The SDK's `AuthInterceptor` is not used, because it applies only the first scheme of a requirement and skips Basic, cookie and query API keys. The gap is recorded in `docs/upstream-gaps.md` as an `a2a-python` PR candidate (credential support for every A2A security scheme and AND requirements).
- Only credential plumbing is added beneath the SDK (headers through `service_parameters`, query parameters and TLS on our transports); A2A messages are never built or altered.
- OAuth tokens are refreshed automatically when expired and a refresh token exists; a 401 with `error="invalid_token"` triggers one refresh-and-retry at the conversation level (a new SDK call, not a replayed request).

## Review Focus

1. **AND requirement** (`[{"apiKey": [], "oauth": ["read"]}]`): both credentials are sent together. *Test:* Task 2 `test_and_requirement_applies_every_scheme`.
2. **Skill-level requirement stricter than the card's:** sending a message whose skill needs a scope the token lacks yields an `auth` error with the agent's 403, not a crash. *Test:* Task 6 `test_skill_scope_enforced`.
3. **Expired token with refresh token:** next call refreshes silently. *Test:* Task 4 `test_expired_token_refreshes_before_call`.
4. **Vault key missing after restart** (keyfile deleted): stored credentials are reported as unreadable, the agent stays usable, the user can re-enter. *Test:* Task 1 `test_unreadable_credentials_are_reported_not_raised`.
5. **Credential never appears in an exchange record or API response.** *Test:* Task 3 `test_secrets_absent_from_exchanges_and_api`.

---

### Task 1: Vault and credential store
Files: `core/auth/{__init__,vault,store}.py`; model `Credential(id, agent_id, scheme_name, kind, encrypted, expires_at, created_at, updated_at)`. Kinds: `api_key`, `http_basic`, `http_bearer`, `oauth2` (token set: access, refresh, expires_at, scopes, token_type, id_token), `mtls` (cert PEM, key PEM, optional CA PEM). `Vault(key: bytes)` with `encrypt(dict) -> bytes`, `decrypt(bytes) -> dict` (raises `VaultError`). `load_vault_key(settings) -> bytes` (env `A2AW_SECRET_KEY` base64/32 bytes, else `<home>/secret.key` created 0600). `CredentialStore(db, vault)`: `put(agent_id, scheme, kind, secret, expires_at=None)`, `get(agent_id, scheme) -> dict | None` (None + `unreadable=True` flag in `list` when decryption fails), `list(agent_id) -> list[CredentialInfo]` (no secrets; masked preview like `••••a91`), `delete(agent_id, scheme)`.
Tests: round-trip, wrong key → VaultError, keyfile permissions 0600, store put/get/list/delete, masked previews, unreadable after key change.

### Task 2: Requirement evaluator and auth applier
Files: `core/auth/requirements.py`, `core/auth/apply.py`. `effective_requirements(card, skill_id=None) -> list[dict[str, list[str]]]` (skill requirements override card's when present). `choose_requirement(requirements, available: set[str]) -> dict | None` (first OR-alternative whose schemes are all available; empty requirement list → `{}` meaning no auth). `AuthPlan(headers: dict, query: dict, tls: TlsMaterial | None, missing: list[str])`. `build_auth_plan(card, credentials: dict[str, dict], skill_id=None) -> AuthPlan` mapping per scheme: apiKey header → header; cookie → `Cookie` header (merged); query → query param; http basic → `Authorization: Basic base64(user:pass)`; http bearer / oauth2 / oidc → `Authorization: Bearer <access_token>`; mutualTLS → tls. `open_client(..., auth: AuthPlan | None)` passes `params=auth.query` and TLS (`verify` + `cert` on httpx; `ssl_channel_credentials(root, key, chain)` for gRPC); call sites merge `auth.headers` into `service_parameters`.
Tests: every scheme mapping, AND requirement, OR fallback, skill override, missing list, cookie merging, TLS material passed to both transports.

### Task 3: Wiring into conversations, tasks, cards, recordings
`ConversationService.send/resubscribe/check_status/cancel`, `TaskService`, extended card all build the plan from the vault. `SendOptions.skill_id` (optional, chooses skill-level requirements). Redaction: `redact_url` already masks known key names; add the agent's API-key query parameter names dynamically (the recorder gets `extra_sensitive_query` from the plan). 401/403 classification already gives `auth`. Extended card call uses the plan (the spec expects it to be authenticated).
Tests: authenticated chat against `auth-apikey` zoo (header/query/cookie variants), Basic, Bearer; 401 when missing; secrets absent from exchanges and API.

### Task 4: OAuth2 and OpenID Connect flows
Files: `core/auth/oauth.py`, `core/auth/oidc.py`, mock IdP `fixtures/idp.py`. Flows: client credentials (`token_url`), password, device code (`device_authorization_url`, poll with `interval`/`slow_down`), authorization code with PKCE S256 (`authorization_url`; state + verifier kept server-side; callback `/oauth/callback`), implicit (`authorization_url`, token from the callback page fragment posted to `/oauth/implicit`). Discovery: `oauth2_metadata_url` (RFC 8414) and OIDC `open_id_connect_url` (`.well-known/openid-configuration`) fill missing endpoints. Refresh: `ensure_fresh(agent_id, scheme)` refreshes when `expires_at` passed. All IdP traffic is recorded (operation `oauth_token`, etc.).
Mock IdP (Starlette): `/.well-known/openid-configuration`, `/.well-known/oauth-authorization-server`, `/authorize` (auto-approve form; honours `response_type=code|token`, PKCE), `/token` (code+verifier, client_credentials, password, refresh_token, device_code with pending → approved), `/device_authorization`, `/device/approve`, `/jwks`; issues RS256 JWTs with `scope`, `exp`.
Tests: each flow end to end against the mock IdP; PKCE verifier mismatch rejected; device code pending then success; refresh on expiry; discovery.

### Task 5: Auth zoo agents
`build_zoo_app(..., auth: Literal["none","apikey-header","apikey-query","apikey-cookie","basic","bearer","oauth","oidc","mtls","and"])` adds a Starlette `AuthenticationMiddleware` backend checking the declared scheme (JWT validated against the mock IdP JWKS for oauth/oidc), declares matching `security_schemes`/`security_requirements` (plus a skill `hold` requiring scope `booking.write`), and the executor enforces skill scopes and emits `auth_required` for `auth` text when no scope. mTLS variant: uvicorn with a generated CA/server cert and `ssl_cert_reqs=CERT_REQUIRED`; gRPC server with `ssl_server_credentials(..., require_client_auth=True)`. Extended card is served only to authenticated callers.
Tests: each variant rejects unauthenticated calls with 401 and accepts correct credentials.

### Task 6: API, CLI, web Security tab
API: `GET /api/agents/{id}/security` (schemes from the card with plain descriptions, requirement alternatives, which are satisfied, credential infos), `PUT /api/agents/{id}/credentials/{scheme}` (api key / basic / bearer / mtls upload / oauth client config), `DELETE …`, `POST /api/agents/{id}/oauth/{scheme}/start {flow}` → `{authorize_url}` or `{user_code, verification_uri}` or `{done}`, `GET /oauth/callback`, `POST /oauth/implicit`, `POST /api/agents/{id}/oauth/{scheme}/refresh`, `POST /api/agents/{id}/security/probe` (unauthenticated call → expect 401; wrong credential → 401/403; skill scope check).
CLI: `auth status <agent>`, `auth set <agent> <scheme> --api-key/--username --password/--token/--cert --key --ca`, `auth login <agent> <scheme> [--flow …] [--client-id --client-secret --scope …]` (prints authorize URL or device code and waits; `--no-input` fails fast), `auth logout`, `auth probe`.
Web: Security tab per the mockup (one card per scheme with sign-in state, method chooser for OAuth flows, PKCE indicator, scopes, expiry, Refresh/Decode token; API key/basic/bearer forms; mTLS upload; "Is it enforced?" probe results), connection menu shows "Signed in"/"Sign-in needed", chat `auth_required` card gets a **Sign in** button that opens the Security tab and, once signed in, a **Continue** button that resumes the task.
Tests: API (credential round trip masked, oauth start/callback against mock IdP), CLI (`auth set` + send works; `auth login --flow client_credentials`), web (Security tab forms, sign-in state, auth_required Continue).

### Task 7: E2E and docs
E2E: connect `auth-oauth` zoo, sign in with auth-code+PKCE through the mock IdP page, chat, see `Signed in`; connect `auth-apikey-query`, paste key, chat; Inspect shows `••••`. Docs: README security section, `docs/upstream-gaps.md` entry for SDK credential support, agents.md auth commands.

## Self-Review
Spec §3 row I covered: all schemes (T2/T5), all five flows + metadata discovery (T4), OIDC (T4), mTLS (T2/T5), AND/OR at card and skill level (T2/T6), `auth_required` resume (T6), Security tab (T6), enforcement probes (T6). Credentials safety (T1/T3). Upstream gap logged (T7).
