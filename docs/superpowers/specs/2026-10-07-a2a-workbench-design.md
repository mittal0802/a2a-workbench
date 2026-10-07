# A2A Workbench — Design

**Date:** 2026-10-07
**Status:** Draft, awaiting review
**License:** Apache-2.0
**UI reference:** [`docs/design/ui-mockup.html`](../../design/ui-mockup.html) (approved direction, v2)

## 1. Goal

A2A Workbench is an open-source developer tool for building and debugging
[A2A](https://a2a-protocol.org) agents end to end. A developer connects any A2A
agent, talks to it in a friendly chat UI, exercises **every feature the A2A
protocol defines**, sees exactly what went over the wire, and gets a health
report that says where the agent deviates from the spec and how to fix it.
A built-in **Assistant** (an LLM the user brings a key for) can call any of the
registered agents as tools, so multi-agent flows can be tested conversationally.

### Principles

1. **Official SDK only.** All protocol traffic goes through `a2a-sdk` (Python,
   `a2aproject/a2a-python`). We never hand-roll A2A requests, types or
   serialization. If the SDK is missing something we need, we contribute it
   upstream (see §11) instead of working around it locally.
2. **Strictly the spec.** Features, labels in Inspect, and health checks map to
   the A2A specification. Every check cites the spec section it enforces.
3. **Friendly first, raw on demand.** Plain-language UI by default. Protocol
   detail (wire frames, field names, spec references) is always one click away
   in Inspect, never in the way.
4. **Local first.** `uvx a2a-workbench` or `docker run` gives a fully working
   instance on localhost with no account and no external services.

### Non-goals (for v1)

- Hosting or registering agents for others (we are a client).
- Protocol versions older than 0.3 (no official SDK support; see §12).
- Displaying agent "reasoning" as a first-class concept (not in the spec; see §12).

## 2. Users and key scenarios

1. **Agent developer, local loop.** Runs the Workbench next to the agent they are
   building, connects `http://localhost:9999`, chats with it, opens Inspect to
   see a malformed artifact update, fixes the code, re-runs the health check.
2. **CI gate.** Runs `a2a-workbench check https://staging.agent.dev --fail-on fail`
   in CI; gets a JSON/HTML report and a non-zero exit when the agent regresses.
3. **Integrator.** Connects a third-party agent that needs OAuth, signs in
   through the browser flow, browses its skills, verifies it actually enforces
   the scopes it advertises.
4. **Multi-agent tester.** Asks the Assistant "find me a compliant flight and
   file the expense"; watches it call Travel and Expenses agents, answer an
   `input_required` question, and retry after an extension error.

## 3. Protocol coverage (the "nothing skipped" inventory)

Source of truth: the protocol definition shipped in `a2a-sdk` 1.2.x
(`lf.a2a.v1`, protocol v1.0) plus its `a2a.compat.v0_3` layer. Every row below
is (a) drivable from the UI, (b) visible in chat/Inspect, (c) covered by
health checks.

| # | Area | Coverage |
|---|---|---|
| A | Discovery | Fetch `/.well-known/agent-card.json` (or an explicit card URL); render every `AgentCard` field (name, description, version, provider, icon_url, documentation_url, default input/output modes, skills with id/tags/examples/modes/**per-skill security requirements**); verify `AgentCardSignature` (JWS, JWKS); `GetExtendedAgentCard` + public/extended diff. |
| B | Transports & versions | JSON-RPC, HTTP+JSON (REST), gRPC, chosen from `supported_interfaces`; user can force any listed interface; `protocol_version` per interface; `A2A-Version` header; `tenant`; v1.0 native, v0.3 via SDK compat (legacy `message/send`, `tasks/resubscribe`, `agent/getAuthenticatedExtendedCard`, …). |
| C | Messaging | `SendMessage`, `SendStreamingMessage`; full `SendMessageConfiguration` (`accepted_output_modes`, `history_length`, `return_immediately`, inline `task_push_notification_config`); both response shapes (Task or Message); `context_id` continuation; `reference_task_ids`; message `metadata` and `extensions`. |
| D | Parts | `text`, `raw` bytes, `url`, `data` (JSON), with `media_type`, `filename`, per-part `metadata`. All are composable (file upload, URL, JSON editor) and renderable (markdown, image/audio/video/PDF preview, JSON tree, download). |
| E | Task lifecycle | All states: submitted, working, completed, failed, canceled, input_required (inline reply), rejected, auth_required (sign-in then resume); status message + timestamp. |
| F | Task operations | `GetTask` (history_length); `ListTasks` (context_id, status, status_timestamp_after, include_artifacts, history_length, page_size/page_token, total_size); `CancelTask` (metadata); `SubscribeToTask`. |
| G | Streaming | `StreamResponse` variants: Task, Message, `TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent` with `append` / `last_chunk` reassembly. |
| H | Push notifications | Create/Get/List (paginated)/Delete `TaskPushNotificationConfig`; built-in webhook receiver; validate `A2A-Notification-Token` and `AuthenticationInfo`; show deliveries in chat and the Notifications tab. |
| I | Security | Schemes: API key (header/query/cookie), HTTP (Basic/Bearer), OAuth2, OpenID Connect, mTLS. OAuth flows: authorization code (+PKCE), client credentials, implicit, password, device code; `oauth2_metadata_url` discovery. `SecurityRequirement` AND/OR semantics at card and skill level. |
| J | Extensions | Show declared extensions (uri, description, required, params); activate per request via `A2A-Extensions`; detect required-extension enforcement. |
| K | Errors | All A2A errors (TaskNotFound, TaskNotCancelable, PushNotificationNotSupported, UnsupportedOperation, ContentTypeNotSupported, InvalidAgentResponse, ExtendedAgentCardNotConfigured, ExtensionSupportRequired, VersionNotSupported) plus JSON-RPC parse/request/method/params/internal, with correct per-binding mapping (JSON-RPC code, HTTP status, gRPC status). |

## 4. Architecture

```
 Browser (React SPA)                      a2a-workbench server (Python)                Target agents
┌──────────────────────┐  REST + WS   ┌──────────────────────────────────────┐  A2A  ┌──────────────┐
│ Chat · About · Tasks │◄────────────►│ api/        FastAPI routes + WS hub  │──────►│ any A2A      │
│ Notifications ·      │              │ registry/   agents, workspaces       │ JSON- │ agent, any   │
│ Security · Health ·  │              │ connection/ SDK ClientFactory +      │ RPC / │ binding,     │
│ Assistant · Inspect  │              │             WireRecorder interceptor │ REST /│ v1.0 / v0.3  │
└──────────────────────┘              │ conversations/ timeline, parts store │ gRPC  └──────┬───────┘
                                      │ auth/       credential vault, OAuth  │              │ push
                                      │ push/       webhook receiver, tunnel │◄─────────────┘
                                      │ health/     check engine + suites    │
                                      │ assistant/  LLM adapters + tool loop │──► Anthropic/OpenAI/Gemini
                                      │ store/      SQLAlchemy (SQLite|PG)   │
                                      └──────────────────────────────────────┘
```

**Why a Python backend:** the Python SDK has the widest coverage (all three
bindings, official v0.3 compat), and OAuth secrets, mTLS keys and webhook
receipt belong server-side. The browser never talks to a target agent
directly, so there are no CORS problems and no secrets in the browser.

**One process.** The server serves the built SPA as static files, the JSON API,
the WebSocket and the webhook endpoints on one port (default `8484`).

### 4.1 Repository layout

```
a2a-workbench/
├── server/                    # Python package `a2a_workbench` (uv)
│   ├── a2a_workbench/
│   │   ├── api/               # FastAPI routers, WS hub, schemas (pydantic)
│   │   ├── registry/          # agent + workspace models/services
│   │   ├── connection/        # SDK client building, interface selection, WireRecorder
│   │   ├── conversations/     # send/stream, timeline normalization, artifact assembly
│   │   ├── auth/              # vault, scheme handlers, OAuth flows, mTLS
│   │   ├── push/              # webhook receiver, token validation, tunnel
│   │   ├── health/            # check registry, passive + active suites, reports
│   │   ├── assistant/         # LLM adapters, tool builder, run loop
│   │   ├── store/             # SQLAlchemy models, Alembic migrations
│   │   ├── cli.py             # `a2a-workbench serve|check`
│   │   └── static/            # built SPA (generated, not committed)
│   └── tests/
├── web/                       # React + TypeScript + Vite (pnpm)
│   └── src/{app,features/<tab>,components,lib}
├── fixtures/                  # "agent zoo": test agents built with a2a-sdk server
├── docs/
├── Dockerfile, docker-compose.yml
└── LICENSE (Apache-2.0), NOTICE, README.md, CONTRIBUTING.md
```

### 4.2 Tech choices

- **Server:** Python 3.12+, `a2a-sdk[grpc,signing,http-server]` pinned to a
  minor (1.2.x) with Renovate updates, FastAPI, SQLAlchemy 2 async, Alembic,
  httpx, `cryptography`, `pyjwt`. Packaging and dev with `uv`.
- **Web:** React 19, TypeScript, Vite, Tailwind CSS (tokens from the mockup as
  CSS variables, light and dark themes), Radix UI primitives, TanStack Query for
  REST, a small typed WS client, Shiki for JSON highlighting.
- **Storage:** SQLite file in `~/.a2a-workbench/` by default; Postgres via
  `DATABASE_URL`.

## 5. Components

### 5.1 `connection/` — talking to agents through the SDK

- `CardService.fetch(url)` uses the SDK `card_resolver` to load the card, then
  verifies signatures with the SDK signing helpers. Result: card + verification
  status + fetch trace.
- `ClientBuilder.build(agent, interface, credentials)` returns an SDK `Client`
  from `ClientFactory` for the chosen binding. For v0.3 interfaces it uses the
  SDK's `compat.v0_3` transports. Auth is applied through SDK auth interceptors
  (`a2a.client.auth`).
- **WireRecorder** captures every exchange for Inspect: an SDK
  `ClientCallInterceptor` for logical calls (method, params, result, error,
  timing), plus httpx event hooks and a gRPC client interceptor for the raw
  layer (URL, headers with secrets redacted, status, body or SSE frames,
  protobuf decoded to JSON). Each exchange gets an id, and timeline events
  reference it so "View raw" jumps to the right frame.

### 5.2 `conversations/` — chat

- A **conversation** maps to one A2A `context_id` on one agent.
- `send(conversation, parts, options)` calls `send_message` (streaming if the
  agent supports it and the option is on). Every SDK event is normalized into a
  `TimelineEvent` (`message`, `task`, `status`, `artifact`, `push`, `error`) and
  pushed over the WS hub, then persisted.
- **ArtifactAssembler** applies `append` / `last_chunk` to build complete
  artifacts while keeping each chunk for Inspect.
- Replies to `input_required` reuse `task_id` + `context_id`. `auth_required`
  opens the Security sign-in flow and then resumes the task.
- Parts: uploads are stored in the blob store (local dir or DB), sent as `raw`
  or `url` per the user's choice, and rendered by `media_type`.

### 5.3 `auth/`

- **Vault:** credentials are encrypted at rest (AES-GCM via `cryptography`).
  The key comes from `A2AW_SECRET_KEY`, or locally from an auto-generated
  keyfile with 0600 permissions. Secrets are never logged and are redacted in
  Inspect.
- Handlers per scheme: API key (header/query/cookie), HTTP Basic/Bearer, OAuth2
  (all five flows; auth code uses a backend callback `/oauth/callback` with
  PKCE; device code shows the user code in the UI; tokens are refreshed
  automatically), OIDC (discovery, ID token shown decoded), mTLS (PEM cert+key
  upload, client TLS context per agent).
- The **requirement evaluator** decides which credentials satisfy a card's or
  skill's `SecurityRequirement` list (OR of ANDs).

### 5.4 `push/`

- Endpoint `POST /hooks/{hook_id}` receives notifications, validates the
  configured token (`A2A-Notification-Token`) and the authentication info, and
  emits a `push` timeline event to the conversation that owns the task.
- **Public URL:** in local mode, an optional tunnel (`cloudflared` quick tunnel
  if it is installed, or a user-supplied `PUBLIC_BASE_URL`); in the hosted
  instance, the server's own public URL.
- Notifications tab: CRUD over the SDK push-config methods, plus the delivery
  inbox.

### 5.5 `health/` — conformance engine

- A **Check** has: `id`, `area` (A–K), `title`, `spec_ref`, `applies(card)`
  (for example, skip streaming checks if `capabilities.streaming` is false, in
  which case the result is `not_supported` and it is not counted against the
  agent), `run(ctx) -> Result`, and a `fix_hint`.
- **Result:** `pass | warn | fail | not_supported | error` with expected,
  actual and the `exchange_ids` of the evidence.
- **Passive checks** run on every live exchange, shown in Inspect › Checks.
  **Active suite** runs probes per area (for example: cancel a completed task
  and expect `TaskNotCancelableError`; ListTasks with `status_timestamp_after`
  and verify the filter). Runs can target one interface or all of them, which
  gives a cross-binding comparison.
- **Score** = round(100 × (pass + 0.5 × warn) ÷ applicable), where applicable
  excludes `not_supported`, and `error` (a Workbench-side failure) is shown
  separately and excluded. **Reports:**
  JSON (stable schema, versioned) and a self-contained HTML file.
- **CLI:** `a2a-workbench check <url> [--interface jsonrpc|rest|grpc|all]
  [--auth-file creds.json] [--format json|html] [--fail-on fail|warn]`. It uses
  the same engine, with no server needed.
- **Safety:** active probes create real tasks. The UI warns before a run, and
  destructive probes (cancel, delete push config) only touch tasks the suite
  created itself.

### 5.6 `assistant/` — orchestrator

- `LLMAdapter` interface: `stream(messages, tools) -> AsyncIterator[Delta]`.
  Implementations: Anthropic (first), OpenAI (also covers OpenAI-compatible
  `base_url`: Ollama, vLLM, LM Studio), Gemini. Users bring their own keys,
  stored in the vault.
- **Tool builder:** each enabled agent becomes a tool `call_<agent>` (input:
  message text, optional data/file refs, optional `task_id` to continue).
  Descriptions are generated from the card and skills. Helper tools:
  `get_task`, `cancel_task`.
- **Run loop:** plan, then tool calls, then results back to the LLM. When an
  agent returns `input_required`, the question goes back to the LLM, which can
  answer it or ask the user. Limits: max steps (default 12), timeouts and token
  budget. Each A2A call is a normal conversation, so "Open this conversation"
  shows it in Chat with full Inspect.

### 5.7 `api/` and the web app

- REST: `/api/agents`, `/api/agents/{id}/card`, `/api/conversations`,
  `/api/tasks`, `/api/push`, `/api/credentials`, `/api/health/runs`,
  `/api/assistant/runs`, `/api/exchanges/{id}`. WS: `/ws` multiplexed by topic
  (`conversation:{id}`, `health-run:{id}`, `assistant-run:{id}`, `hooks`).
- Web routes follow the mockup: sidebar (Assistant, Health checks,
  Notifications, agents list, Connect an agent); agent page with tabs Chat ·
  About · Tasks · Notifications · Security · Health; Inspect drawer; connection
  popover (interface, version, sign-in); Options menu in the composer (every
  `SendMessageConfiguration` field, plus extensions, metadata and references).
- Plain-language labels with the protocol name as secondary text (for example
  "Needs your input" with `input_required` in the tooltip and in Inspect).

## 6. Data model (SQLAlchemy)

`workspace` (id, name). Local mode has one default workspace. All rows below
carry `workspace_id` so a multi-user hosted mode can be added without
migrating data.

- `agent` (id, name, emoji, base_url, card_json, extended_card_json,
  card_verified, selected_interface, created/updated)
- `credential` (id, agent_id, scheme_name, kind, encrypted_blob, expires_at)
- `conversation` (id, agent_id, context_id, title, origin = chat|assistant|health)
- `task_snapshot` (agent_id, task_id, context_id, state, last_json, updated_at)
- `timeline_event` (id, conversation_id, seq, kind, payload_json, exchange_id, ts)
- `exchange` (id, agent_id, method, binding, request, response, frames, status, timing). Retention cap configurable (default 7 days or 5k rows).
- `blob` (id, media_type, filename, bytes|path)
- `push_hook` (id, agent_id, task_id, config_id, token_hash, auth_json)
- `health_run` (id, agent_id, interface, protocol_version, started/finished, score, report_json)
- `assistant_run` (id, provider, model, steps_json, status)

## 7. Error handling

- Every SDK exception becomes a timeline `error` event classified as
  **transport** (DNS/TLS/timeout), **protocol** (A2A/JSON-RPC error with
  code/message/data), **auth** (401/403, which offers sign-in), or **workbench**
  (our bug). Nothing is swallowed. Each error links to its exchange.
- Malformed responses the SDK rejects are still recorded raw by WireRecorder,
  so the user sees *what* the agent sent, and a health finding is created.
- The WS reconnects with resume-from-seq, so no timeline events are lost when
  the browser reconnects.

## 8. Security of the Workbench itself

- **Local mode:** binds to `127.0.0.1` by default, with no login. Private and
  loopback agent URLs are allowed, since that is the main use case.
- **Hosted instance** (operated only by the project maintainers): see Phase 7.
  It requires sign-in, and its SSRF guard blocks private, link-local and
  metadata IP ranges. It also adds per-user rate limits and probe concurrency
  limits, uses a secret key from the environment, and runs on Postgres.
- Webhook endpoints use unguessable ids, and tokens are compared in constant
  time.

## 9. Testing strategy

- **Agent zoo (`fixtures/`):** small agents built with the official `a2a-sdk`
  server components, runnable in-process for tests and via
  `a2a-workbench fixtures` for manual demos:
  - `compliant-v1`: every capability, all three bindings, signed card, extended card, push, extensions
  - `legacy-v03`: the same, on protocol v0.3
  - `auth-*`: one per scheme and flow, plus a local mock OAuth/OIDC provider
  - `broken-*`: deliberately violate specific rules (wrong error codes,
    ignored filters, unclosed streams, bad chunks, unsigned card) so each
    health check is proven to **detect** the failure, not just pass on good
    servers
- **Server:** pytest + pytest-asyncio. Unit tests per module, integration
  tests against the zoo, golden tests for report JSON.
- **Web:** Vitest + Testing Library for components. Playwright E2E against the
  server and zoo: connect, chat, stream, input_required, Inspect, health run,
  Assistant with a mocked LLM.
- **CI:** GitHub Actions (lint ruff/mypy/eslint/tsc, tests, build Docker
  image).

## 10. Distribution

- `uvx a2a-workbench` / `pipx install a2a-workbench` (PyPI wheel bundles the
  built SPA).
- `docker run -p 8484:8484 ghcr.io/<owner>/a2a-workbench`. `docker-compose.yml`
  for Postgres and the hosted setup.
- Config via env or `~/.a2a-workbench/config.toml`: `A2AW_HOST`, `A2AW_PORT`,
  `DATABASE_URL`, `A2AW_SECRET_KEY`, `PUBLIC_BASE_URL`, `A2AW_MODE=local|hosted`.

## 11. Upstream contributions

When work hits a gap in `a2a-sdk` or the spec, we log it in
`docs/upstream-gaps.md` (what is missing, why we need it, a proposed API).
SDK gaps become PRs to `a2aproject/a2a-python`. Spec gaps (for example a
standard reasoning/thought part) become extension proposals or discussions in
`a2aproject/A2A`. Nothing is opened upstream without maintainer sign-off.

## 12. Phased delivery

Each phase gets its own implementation plan and ends shippable.

**Phase 1 — Foundation, connect, chat (JSON-RPC, v1.0)**
Repo scaffold (uv + pnpm, lint, CI, Apache-2.0), single-process server
serving the SPA, SQLite store, design tokens and app shell (sidebar, theme
toggle). Connect flow (fetch card, verify signature, pick interface). About
tab. Chat with send and stream, all Part types, `input_required` reply, stop
task, and the Options menu. Inspect drawer with WireRecorder. Agent zoo:
`compliant-v1` (JSON-RPC). Packaging: `uvx` and Docker.

**Phase 2 — Every binding and version**
REST and gRPC bindings, v0.3 compat, connection popover switching. Tasks tab
(Get/List with every filter and pagination, Subscribe, Cancel). Extended card
and diff. Extensions activation. Zoo: `compliant-v1` on all bindings,
`legacy-v03`.

**Phase 3 — Security**
Vault, all schemes and all OAuth flows, OIDC, mTLS, requirement evaluator,
`auth_required` resume, Security tab. Zoo: `auth-*` and the mock IdP.

**Phase 4 — Push notifications**
Push config CRUD, webhook receiver, token and auth validation, tunnel
support, Notifications tab and inbox, push events in chat.

**Phase 5 — Health**
Check engine, passive checks in Inspect, active suites for areas A–K,
cross-interface runs, Health tab and global Health checks page, JSON/HTML
reports, `a2a-workbench check` CLI. Zoo: `broken-*` agents, with one or more
per check.

**Phase 6 — Assistant**
LLM adapters (Anthropic, then OpenAI + compatible, then Gemini), tool builder,
run loop, step UI, limits.

**Phase 7 — Hosted instance and v1.0 release**
Hosted mode (sign-in, per-user workspaces, SSRF guard, rate limits,
Postgres), docs site, PyPI and GHCR publishing, v1.0.0 tag.

**After v1 (candidates):** reasoning/thought display through known
metadata/extension conventions, plus the upstream proposal; protocol
versions before 0.3 via isolated legacy-SDK worker processes; a cross-check
using `@a2a-js/sdk` as a second client.

## 13. Assumptions to confirm

1. "Only we will host this" means: anyone can run it locally from the
   open-source repo, and the single public hosted instance is run by the
   project maintainers. That instance's sign-in method (for example GitHub
   OAuth) is decided in Phase 7.
2. The GitHub repo lives under your personal account as `a2a-workbench`.
   Commits should use your personal git identity, not your work one.
