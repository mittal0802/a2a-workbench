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
5. **One core, three front-ends.** Everything lives in a UI-independent core
   library. The web app, the CLI and the MCP server are thin layers over it, so
   any feature available in the browser is also available to scripts, CI and
   AI agents such as Claude Code.
6. **Test the unhappy paths too.** Connection drops, timeouts, resets and
   garbled responses are first-class test inputs, injected beneath the SDK, so
   recovery behaviour such as `SubscribeToTask` after a dropped stream can be
   verified deliberately rather than by luck.

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
4. **Resilience tester.** Turns on "drop the connection after 3 events" for a
   long streaming task, watches the stream break, clicks **Resubscribe**, and
   verifies the agent replays the current task state and continues; then runs
   the Resilience health suite to check this for every binding.
5. **AI agent as tester.** A developer asks Claude Code "test my A2A server on
   localhost:9999". Claude calls `a2a-workbench check http://localhost:9999
   --json` (or the MCP tools), reads the structured findings, and fixes the
   server code, iterating until the suite passes.
6. **Multi-agent tester.** Asks the Assistant "find me a compliant flight and
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
| H | Push notifications | Create/Get/List (paginated)/Delete `TaskPushNotificationConfig`; built-in webhook receiver; validate `AuthenticationInfo` (the `Authorization` header) and the config token (the SDK sends it as `X-A2A-Notification-Token`; A2A names no header); show deliveries in chat and the Notifications tab. |
| I | Security | Schemes: API key (header/query/cookie), HTTP (Basic/Bearer), OAuth2, OpenID Connect, mTLS. OAuth flows: authorization code (+PKCE), client credentials, implicit, password, device code; `oauth2_metadata_url` discovery. `SecurityRequirement` AND/OR semantics at card and skill level. |
| J | Extensions | Show declared extensions (uri, description, required, params); activate per request via `A2A-Extensions`; detect required-extension enforcement. |
| K | Errors | All A2A errors (TaskNotFound, TaskNotCancelable, PushNotificationNotSupported, UnsupportedOperation, ContentTypeNotSupported, InvalidAgentResponse, ExtendedAgentCardNotConfigured, ExtensionSupportRequired, VersionNotSupported) plus JSON-RPC parse/request/method/params/internal, with correct per-binding mapping (JSON-RPC code, HTTP status, gRPC status). |
| L | Resilience & failure handling | Client-side faults injected under the SDK: connection refused, DNS/TLS failure, connect/read timeout, slow responses, TCP reset, stream dropped after N events or N seconds, truncated/garbled bodies, HTTP 429/5xx, token expiry mid-stream. Verified recovery: `SubscribeToTask` after a dropped stream (current Task delivered first, then later events, nothing duplicated or lost); `GetTask` polling as a fallback; task keeps running when the client disconnects; terminal-state streams end correctly; retries with the same `message_id`; push delivery when the stream is gone. |

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

**Core vs. front-ends.** Every module in the diagram except `api/` belongs to
`a2a_workbench.core` and has no FastAPI or web dependency. Three front-ends
use it:

```
              ┌── api/   (FastAPI + WS) ──► web SPA
 core ────────┼── cli/   (Typer)        ──► humans, scripts, CI
              └── mcp/   (MCP stdio/HTTP) ─► Claude Code and other AI agents
```

The CLI and the MCP server run standalone, with no web server needed. They
share the same state directory and database as the web app, so an agent
registered from the CLI shows up in the UI, and a health run started by Claude
can be opened in the browser.

### 4.1 Repository layout

```
a2a-workbench/
├── server/                    # Python package `a2a_workbench` (uv)
│   ├── a2a_workbench/
│   │   ├── core/
│   │   │   ├── registry/      # agent + workspace models/services
│   │   │   ├── connection/    # SDK client building, interface selection, WireRecorder
│   │   │   ├── faults/        # fault-injecting httpx transport + gRPC interceptor
│   │   │   ├── conversations/ # send/stream, timeline normalization, artifact assembly
│   │   │   ├── auth/          # vault, scheme handlers, OAuth flows, mTLS
│   │   │   ├── push/          # webhook receiver, token validation, tunnel
│   │   │   ├── health/        # check registry, passive + active suites, reports
│   │   │   ├── assistant/     # LLM adapters, tool builder, run loop
│   │   │   └── store/         # SQLAlchemy models, Alembic migrations
│   │   ├── api/               # FastAPI routers, WS hub, schemas (pydantic)
│   │   ├── cli/               # Typer app: every core operation as a command
│   │   ├── mcp/               # MCP server exposing core operations as tools
│   │   ├── fixtures/          # "agent zoo": test agents built with the a2a-sdk server
│   │   └── static/            # built SPA (generated, not committed)
│   └── tests/
├── web/                       # React + TypeScript + Vite (pnpm)
│   └── src/{app,features/<tab>,components,lib}
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
  `TimelineEvent` (`message`, `task`, `status`, `artifact`, `push`, `error`,
  `fault`, `connection_lost`, `recovered`) and
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
  authentication info (`Authorization`, A2A §4.3.3) and the configured token
  (sent by the SDK as `X-A2A-Notification-Token`; A2A does not name the header,
  see `docs/upstream-gaps.md`), and emits a `push` timeline event to the
  conversation that owns the task.
- **Public URL:** in local mode, an optional tunnel (`cloudflared` quick tunnel
  if it is installed, or a user-supplied `PUBLIC_BASE_URL`); in the hosted
  instance, the server's own public URL.
- Notifications tab: CRUD over the SDK push-config methods, plus the delivery
  inbox.

### 5.5 `health/` — conformance engine

- A **Check** has: `id`, `area` (A–L), `title`, `spec_ref`, `applies(card)`
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
- **CLI:** `a2a-workbench check` (see §5.9) runs the same engine with no
  server needed.
- **Safety:** active probes create real tasks. The UI warns before a run, and
  destructive probes (cancel, delete push config) only touch tasks the suite
  created itself.

### 5.6 `assistant/` — agent-calling mode

The Assistant is an orchestrator LLM acting as an A2A **client agent**: it
calls registered agents the way the A2A specification defines a client
agent should. Every rule below cites the spec section it follows; behaviour
the spec leaves to the client (how results are presented to the user) is a
user setting, not a protocol feature.

- **LLM adapters.** `LLMAdapter.stream(messages, tools) -> AsyncIterator[Delta]`.
  Anthropic, OpenAI (also any OpenAI-compatible `base_url`: Ollama, vLLM,
  LM Studio) and Gemini. Keys are the user's own, stored in the vault.
- **Discovery and connection.** The orchestrator knows an agent only through
  its Agent Card (§8.1; Opaque Execution, §1.2). Interface selection follows
  §8.3.2 (first supported `supportedInterfaces` entry, its URL and exact
  `tenant`); the SDK sends `A2A-Version` (§3.6.1). Credentials come from the
  card's `securitySchemes`/`securityRequirements` and are sent on every
  request (§7.3). Optional features are used only when `capabilities`
  declares them (§3.3.4).
- **Tool per agent.** Name derived from the card `name`. The description is
  built only from card fields: `description`, `defaultInputModes`,
  `defaultOutputModes`, and for each skill `id`, `name`, `description`,
  `tags`, `examples`, `inputModes`, `outputModes`. Inputs map one-to-one to
  `Message` / `SendMessageConfiguration` fields:
  - `parts` (text, data, file), checked against the declared input modes;
  - `context_id`, accepted only if the agent returned it earlier
    (clients SHOULD NOT generate one, §3.4.1);
  - `task_id`, accepted only for a non-terminal task (§3.4.2, §3.4.3); a
    terminal task is immutable, so the tool tells the LLM to send a follow-up
    in the same `context_id` with `reference_task_ids` instead
    ("Life of a Task": Task Refinements, Task Immutability);
  - `reference_task_ids` (§3.4.3 SHOULD for follow-ups);
  - `accepted_output_modes`, the media types the orchestrator can use.
  There is no skill selector: `Message` has no skill field, so the agent
  chooses the skill. Skills inform which agent to call and how to phrase the
  request.
  Helper tools: `get_task`, `cancel_task`.
- **Delivery (§3.2.2, §3.5).** `SendStreamingMessage` when
  `capabilities.streaming`, otherwise blocking `SendMessage`. Long tasks may
  use `return_immediately` followed by `SubscribeToTask`, `GetTask` polling or
  push notifications (when declared). A dropped stream is recovered with
  `SubscribeToTask` (§3.5.2).
- **Results (§3.7).** A `Message` reply yields its parts and `context_id`. A
  `Task` reply yields state, status message and **artifacts as the result**;
  status messages are communication, not reliable delivery. An agent that
  returns its output only in messages gets a §3.7 SHOULD warning.
- **Multi-turn.** `input_required`: continue with the same `task_id` and
  `context_id` (§3.4.3). Terminal states (`completed`, `failed`,
  `canceled`, `rejected`): follow-ups are new tasks in the same context with
  `reference_task_ids`. Several tasks may run in parallel in one context
  ("Parallel Follow-ups").
- **`auth_required` (§7.6.2).** The Workbench delegates to the human: the run
  pauses showing the agent's status message, with Sign in and Reply actions.
  While paused it keeps the task observed (Subscribe, or Get Task polling),
  because the agent may continue without a follow-up message.
- **Extensions.** Only extensions the user enabled are sent; an agent's
  `ExtensionSupportRequiredError` is shown as returned.
- **Response mode (user setting).** A2A does not define how a client agent
  presents results to its user, so this is the user's choice, per run (CLI
  `--response-mode`, MCP `response_mode`), with a per-agent default:
  - **Rewrite** — agent output goes to the LLM as the tool result; the user
    sees the Assistant's answer. The agent's verbatim output stays visible in
    the step timeline.
  - **Pass-through** — the agent's output is streamed straight to the user as
    that agent's turn, attributed to it: status messages, artifacts as they
    arrive (files downloadable as delivered, data shown as JSON), and
    `input_required` questions in the agent's own words (the user's reply goes
    to the agent on the same task). The same content is appended to the LLM's
    context, marked as already shown to the user, so the LLM keeps full
    context, does not repeat it, and continues orchestrating (further calls or
    a short follow-up).
  In both modes every answer to an `input_required` question is attributed
  (user or Assistant) in the timeline.
- **Run loop and limits.** Plan, tool calls, results back to the LLM, until
  the LLM finishes, the run pauses for the user, or a limit is hit (max steps,
  default 12; per-call and run timeouts; token budget).
- **Visibility.** Every A2A call is an ordinary conversation
  (`origin = assistant`) with full Inspect, faults and resubscribe, so the
  user sees exactly which `task_id`, `context_id` and references the
  orchestrator used, and when it broke the rules above.
- **Surfaces.** Web: Assistant page with a step timeline and the response-mode
  switch. CLI: `a2a-workbench assist "<goal>" --agents a,b --provider anthropic
  [--response-mode rewrite|pass-through] --json` (NDJSON steps). MCP: `assist`.

### 5.6.1 Integrate tab — calling an agent from your own agent

Per agent, generated from its card and following the same rules as §5.6:

- **Code** for the plain `a2a-sdk` client (resolve card, authenticate with the
  card's schemes, send/stream, `input_required` continuation, follow-ups with
  `reference_task_ids`, resubscribe after a dropped stream, artifacts as
  results, `auth_required` delegated to the caller), and wrappers around it
  for Google ADK (`RemoteA2aAgent`), LangGraph/LangChain (tool), OpenAI Agents
  SDK and Claude Agent SDK (function tools). Secrets are read from environment
  variables, never written into the code. Each rule in the generated code
  carries a comment citing its spec section. The plain-SDK snippet runs in CI
  against the zoo; the wrappers are checked for syntax and imports.
- **Presentation guidance.** A2A leaves presentation to the client; the guide
  describes both response modes and recommends passing artifacts through
  as-is, attributing agent questions, and never answering an agent's
  questions with invented details.
- **Readiness.** Missing REQUIRED `AgentSkill` fields (`id`, `name`,
  `description`, `tags`) are spec issues. Everything else is advice, never a
  failure: skills without `examples`, missing input/output modes, a vague or
  very long description, usage instructions in the description instead of
  skills, an extended card declared but not configured.
- **Surfaces.** Web: Integrate tab. CLI: `a2a-workbench integrate <agent>
  --target sdk|adk|langgraph|openai|claude`. MCP: `integration_guide`.

### 5.7 `faults/` — failure injection and recovery

- **Where:** beneath the SDK, through its own injection points:
  `ClientConfig.httpx_client` gets an httpx client whose transport is a
  `FaultTransport` wrapping the real one, and `ClientConfig.grpc_channel_factory`
  returns a channel with a `FaultInterceptor`. The SDK still builds and parses
  every A2A message; we only disturb the bytes and the connection.
- **Fault profile** (JSON, also exposed in the UI and the CLI): a list of rules
  `{match: {method?, binding?, nth_call?}, fault: <kind>, params}`. Kinds:
  `refuse`, `dns_fail`, `tls_fail`, `connect_timeout`, `read_timeout`,
  `delay(ms)`, `reset`, `drop_stream(after_events|after_ms)`,
  `truncate(bytes)`, `garble`, `http_status(code, retry_after?)`,
  `expire_token`. Rules can fire once, every time, or with a probability, and
  the probability mode takes a seed so runs are reproducible.
- **Recovery helpers:** after a drop, the timeline shows "Connection lost"
  with **Resubscribe** (`SubscribeToTask`) and **Check status** (`GetTask`)
  actions. An optional auto-recover policy (resubscribe with backoff) lets
  users test the agent the way a real client would use it.
- **Gap analysis on recovery:** the Workbench compares events seen before the
  drop with what resubscribe delivers. It flags anything missing, duplicated
  or out of order, and checks that the first event after resubscribing is the
  current `Task`.
- **UI:** a "Network conditions" section in the Options menu (presets: Stable,
  Flaky stream, Slow agent, Offline, Custom profile) and a banner while a
  profile is active. Every injected fault is labelled in Inspect, so it is
  never mistaken for an agent bug.
- **Agent-side faults** that cannot be injected from the client (for example
  "the agent process restarts mid-task") are covered by `flaky-*` zoo agents
  (§9) and documented as a manual recipe for users' own servers.

### 5.8 `api/` and the web app

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

### 5.9 `cli/` and `mcp/` — for humans, CI and AI agents

**CLI** (`a2a-workbench`, Typer). There is a command for every core operation,
so anything the UI can do, a script or an agent can do too:

```
a2a-workbench serve                      # web UI on :8484
a2a-workbench agents add|list|remove     # shared registry with the UI
a2a-workbench card <url|agent> [--extended] [--verify]
a2a-workbench send <agent> "text" [--file f] [--data json] [--stream]
                   [--context-id …] [--task-id …] [--history-length N]
                   [--accept text/plain,…] [--return-immediately]
                   [--extension uri] [--metadata json] [--interface rest]
a2a-workbench tasks get|list|cancel|subscribe …   # every filter as a flag
a2a-workbench push create|get|list|delete …  ;  a2a-workbench push listen
a2a-workbench auth login|status|logout <agent> [--scheme …] [--flow …]
a2a-workbench check <url|agent> [--area A,F,L] [--interface all]
                   [--faults profile.json] [--fail-on fail|warn]
                   [--format json|html|text] [--out report.html]
a2a-workbench faults presets|validate <profile.json>
a2a-workbench fixtures [--zoo compliant-v1,broken-cancel]  # run test agents
a2a-workbench mcp [--transport stdio|http]
```

**Agent-friendly contract:**
- `--json` on every command gives one JSON document. Streaming commands emit
  **NDJSON**, one event per line, in the same `TimelineEvent` shape the UI
  uses.
- **Stable exit codes:** 0 ok, 1 checks failed, 2 usage error, 3 connection
  error, 4 auth error, 5 protocol error, 6 internal error.
- **Never interactive** when stdin is not a TTY or `--no-input` is set.
  Credentials come from flags, env vars (`A2AW_AUTH_<AGENT>_…`) or
  `--auth-file`. Interactive OAuth flows print the URL or device code and wait.
- Findings carry `check_id`, `spec_ref`, `expected`, `actual`, `fix_hint` and
  `exchange_ids`, so an AI agent can act on them without scraping text.
- `a2a-workbench <cmd> --help` includes copy-pasteable examples.
  `docs/agents.md` and a ready-made **Claude Code skill** show an AI agent how
  to test a server and interpret the report.

**MCP server** (`a2a-workbench mcp`, using the official `mcp` Python SDK).
It exposes the same operations as tools for Claude Code, Claude Desktop and
other MCP clients: `fetch_card`, `send_message`, `get_task`, `list_tasks`,
`cancel_task`, `subscribe_task`, `push_*`, `run_health_check`,
`get_exchange`, `list_findings`. Tool results return the structured JSON
above. Long runs stream progress notifications.

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
- `fault_profile` (id, name, rules_json, seed, builtin) — presets ship as builtin rows
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
  - `flaky-*`: server-side failures the client can't inject: the process
    restarts mid-task (in-memory vs. persistent task store), slow or stalled
    streams, resubscribe that replays the wrong state, push endpoint retries
- **Fault-injection tests:** every fault kind is tested against
  `compliant-v1` on every binding. This proves that recovery works (stream
  dropped after N events, then resubscribe, then a complete and
  de-duplicated timeline) and that each failure is reported in the right
  class (transport, protocol or auth).
- **CLI and MCP:** snapshot tests of `--json`/NDJSON output and exit codes,
  plus an MCP client test that drives a full health run over stdio.
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
- `docker run -p 8484:8484 ghcr.io/mittal0802/a2a-workbench`. `docker-compose.yml`
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

Each phase gets its own implementation plan and ends shippable. **Every
phase delivers its features in all three surfaces:** core first, then the
web UI, the CLI commands, and (from Phase 2) the MCP tools, each with tests.

**Phase 1 — Foundation, connect, chat (JSON-RPC, v1.0)**
Repo scaffold (uv + pnpm, lint, CI, Apache-2.0), single-process server
serving the SPA, SQLite store, design tokens and app shell (sidebar, theme
toggle). Connect flow (fetch card, verify signature, pick interface). About
tab. Chat with send and stream, all Part types, `input_required` reply, stop
task, and the Options menu. Inspect drawer with WireRecorder. CLI: `serve`,
`agents`, `card`, `send` (with NDJSON streaming), `--json` and exit codes.
Agent zoo: `compliant-v1` (JSON-RPC). Packaging: `uvx` and Docker. The schema is created with `create_all`;
Alembic migrations arrive in Phase 7, before the first public release.

**Phase 2 — Every binding and version, tasks, and failure injection**
REST and gRPC bindings, v0.3 compat, connection popover switching. Tasks tab
(Get/List with every filter and pagination, Subscribe, Cancel). Extended card
and diff. Extensions activation. **Faults layer** (FaultTransport,
FaultInterceptor, profiles and presets, Network conditions UI, "Connection
lost → Resubscribe / Check status" with gap analysis). CLI: `tasks`,
`--faults`, `faults`. **MCP server** with the tools available so far. Zoo:
`compliant-v1` on all bindings, `legacy-v03`, `flaky-*`.

**Phase 3 — Security**
Vault, all schemes and all OAuth flows, OIDC, mTLS, requirement evaluator,
`auth_required` resume, Security tab. Zoo: `auth-*` and the mock IdP.

**Phase 4 — Agent-calling mode (Assistant) and Integrate**
LLM adapters (Anthropic, then OpenAI + compatible, then Gemini), tool builder
from the card, run loop with the §5.6 rules, response modes (rewrite and
pass-through), step UI, limits, Integrate tab with generated code for the
plain SDK, ADK, LangGraph/LangChain, OpenAI Agents SDK and Claude Agent SDK.
CLI `assist` and `integrate`, MCP `assist` and `integration_guide`. Tests use
a scripted mock LLM against the zoo.

**Phase 5 — Push notifications**
Push config CRUD, webhook receiver, token and auth validation, tunnel
support, Notifications tab and inbox, push events in chat.

**Phase 6 — Health**
Check engine, passive checks in Inspect, active suites for areas A–L
(including the Resilience suite, which runs fault profiles), cross-interface
runs, Health tab and global Health checks page, JSON/HTML reports,
`a2a-workbench check` CLI and the `run_health_check` MCP tool, `docs/agents.md`
and the Claude Code skill. Zoo: `broken-*` agents, with one or more per check.

**Phase 7 — Hosted instance and v1.0 release**
Split by the maintainer's decision (2026-10-12):
- **7a — v1.0 release:** Alembic migrations (with in-place upgrade of pre-1.0
  databases), Postgres support, docs site, PyPI and GHCR publishing, v1.0.0 tag.
- **7b — Hosted instance:** hosted mode (GitHub OAuth sign-in, per-user
  workspaces, SSRF guard, rate limits, probe concurrency limits) on Postgres.

**After v1 (candidates):** reasoning/thought display through known
metadata/extension conventions, plus the upstream proposal; protocol
versions before 0.3 via isolated legacy-SDK worker processes; a cross-check
using `@a2a-js/sdk` as a second client.

## 13. Assumptions to confirm

1. "Only we will host this" means: anyone can run it locally from the
   open-source repo, and the single public hosted instance is run by the
   project maintainers. That instance's sign-in method (for example GitHub
   OAuth) is decided in Phase 7.
2. The GitHub repo is `github.com/mittal0802/a2a-workbench`, and every
   commit is authored as `Keshav Mittal <mittalkeshav41@gmail.com>`.
