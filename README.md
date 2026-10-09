# A2A Workbench

Debug, test and conformance-check any [A2A](https://a2a-protocol.org) agent: a friendly web UI, a CLI built for scripts, CI and AI agents, and an MCP server, all speaking A2A exclusively through the official [`a2a-sdk`](https://github.com/a2aproject/a2a-python).

- **Connect** any agent by URL: the agent card is fetched, its JWS signature verified, and you choose the interface (JSON-RPC, REST or gRPC) and protocol version (1.0, or 0.3 through the SDK's compat layer).
- **Chat** with it using every part type (text, files, URLs, JSON data) and every `SendMessageConfiguration` option, stream replies live, answer `input_required` questions, stop tasks.
- **Tasks**: get, list (every filter, pagination), subscribe and cancel.
- **Break the connection on purpose**: inject faults beneath the SDK (dropped streams, latency, resets) and check that resubscribe gets you back in sync.
- **Sign in** with every security scheme the spec defines, and check the agent actually enforces it.
- **Inspect** every request, response and server-sent event that went over the wire, with secrets redacted; copy or export it as JSON.
- **Push notifications**: manage a task's push configs (create, get, list, delete) and receive the agent's webhooks in a built-in receiver that checks them as the spec requires; every delivery shows in the chat and a Notifications inbox.
- **Agent-calling mode**: an Assistant (Anthropic, OpenAI or any OpenAI-compatible server, Gemini; your own key) calls your agents as tools, exactly the way the A2A spec defines a client agent, so you can test how your agent behaves when another agent calls it.
- **Integrate**: copy-ready code for calling an agent from the plain `a2a-sdk`, Google ADK, LangGraph, the OpenAI Agents SDK or the Claude Agent SDK, plus advice on how ready the card is for agent callers.
- **Script it**: every action is also a CLI command with `--json` / NDJSON output and stable exit codes, and an MCP tool for AI agents.

> Status: Phase 5 of 7 (push notifications). See the [design spec](docs/superpowers/specs/2026-10-07-a2a-workbench-design.md) for the roadmap: push notifications, health checks, and the hosted instance.

## Quick start

```bash
uvx a2a-workbench serve --open        # web UI on http://127.0.0.1:8484
# or
docker run -p 8484:8484 -v a2aw:/data ghcr.io/mittal0802/a2a-workbench
```

No agent at hand? Start the built-in reference agent and connect `http://127.0.0.1:9999`:

```bash
uvx a2a-workbench fixtures
```

## CLI

```bash
a2a-workbench card http://localhost:9999 --json          # fetch + verify the agent card
a2a-workbench agents add http://localhost:9999           # register (shared with the web UI)
a2a-workbench send "Zoo agent" "stream" --json           # NDJSON timeline events
a2a-workbench tasks list "Zoo agent" --status working --json
a2a-workbench send "Zoo agent" "long" --faults flaky_stream --json   # then: resubscribe
a2a-workbench send http://localhost:9999 "inspect" \
  --file report.pdf --data '{"n": 1}' --accept application/json \
  --history-length 5 --extension https://example.com/ext/x --metadata '{"k": "v"}'
```

Exit codes: `0` ok, `1` checks failed, `2` usage error, `3` connection error, `4` auth error, `5` protocol error, `6` internal error.

State lives in `~/.a2a-workbench/` (override with `A2AW_HOME`; database with `DATABASE_URL`).

The server only answers to `localhost`, `127.0.0.1`, `::1` and its bind host, and rejects cross-site `Origin`s, so web pages you visit cannot reach it (DNS-rebinding protection). To open it under another name, set `A2AW_ALLOWED_HOSTS=workbench.lan,10.0.0.5`.

## Security and sign-in

The Security tab (and `a2a-workbench auth …`, and the MCP `auth_*` tools) reads the agent card's `securitySchemes` and `securityRequirements`, including skill-level requirements, and applies them exactly as declared:

| Scheme | How you sign in | How it is sent |
|---|---|---|
| API key | paste the key | header, query parameter or cookie, as the card says |
| HTTP Basic / Bearer | username and password, or a token | `Authorization` header |
| OAuth 2.0 client credentials, password | client ID and secret (and username/password) | `Authorization: Bearer`, renewed before expiry |
| OAuth 2.0 authorization code | browser sign-in with PKCE (S256) | same |
| OAuth 2.0 device code | a code you enter on another device | same |
| OAuth 2.0 implicit (deprecated) | browser sign-in | same |
| OpenID Connect | browser sign-in via the discovery document | same |
| Mutual TLS | client certificate and key (PEM) | presented on the TLS connection (HTTP and gRPC) |

Requirements are evaluated as the spec defines them: the alternatives are OR, the schemes inside one alternative are AND and are all sent together. OAuth endpoints missing from the card are discovered from `oauth2MetadataUrl` (RFC 8414) or the OpenID configuration. When a sign-in fails, the provider's error is shown along with what its published metadata says it supports.

For browser sign-in, register `http://127.0.0.1:8484/oauth/callback` (web UI) or `http://127.0.0.1:8765/oauth/callback` (CLI, `--redirect-port`) as a redirect URI with the provider.

```bash
a2a-workbench auth status "My agent"
A2AW_API_KEY=… a2a-workbench auth set "My agent" apiKey
A2AW_CLIENT_SECRET=… a2a-workbench auth login "My agent" oauth --client-id "$ID" --scope a2a:invoke
a2a-workbench auth login "My agent" oauthCode --client-id "$ID"       # opens your browser
a2a-workbench auth probe "My agent" --json                             # is it enforced?
a2a-workbench auth logout "My agent" oauth
```

Secrets never need to be command-line arguments (which end up in shell history and `ps`): use `A2AW_API_KEY`, `A2AW_TOKEN`, `A2AW_ACCESS_TOKEN`, `A2AW_PASSWORD` or `A2AW_CLIENT_SECRET`, or pass `-` to read the value from standard input.

**Is it enforced?** The probe calls `GetTask` with a random task ID three times: with no credentials, with wrong ones and with yours. An agent that answers the first two with anything but an authentication error does not enforce what its card declares.

Credentials are encrypted at rest (AES-GCM) with `A2AW_SECRET_KEY`, or a key generated in `~/.a2a-workbench/secret.key` (mode 0600). They are never logged, never returned by the API (only masked previews such as `••••a91`), and redacted in every recorded exchange.

## Push notifications

Turn on **Notify me by webhook** in a message's options (or `send --push`), or create a config for any task in the **Notifications** tab (`a2a-workbench push create <agent> <task>`). The Workbench creates a webhook at `/hooks/<id>` with its own token and Bearer credential, puts them in the config (A2A §3.2.2 / §3.1.7), and checks every POST the agent makes:

- `Authorization` must match the config's credentials (A2A §4.3.3, §13.2), else 401;
- the token, when sent, must match (A2A defines the `token` field but not its header; the SDK sends `X-A2A-Notification-Token`, a missing token is only noted);
- the body must be an A2A `StreamResponse` for the task the webhook was created for (§4.3.3), else 400;
- repeats are acknowledged and flagged as duplicates; more than 60 a minute get 429.

Accepted notifications appear as cards in the task's conversation and update its progress; every delivery, accepted or rejected, is in the Notifications inbox with its reasons, masked headers and payload. Webhook secrets are stored only as hashes and masked everywhere.

Agents on other machines cannot reach `127.0.0.1`: set `PUBLIC_BASE_URL`, enter a public URL in **Settings**, or start a Cloudflare quick tunnel there (needs `cloudflared`).

```bash
a2a-workbench send "My agent" "long job" --push --no-stream --return-immediately
a2a-workbench push list "My agent" <task-id> --json
a2a-workbench push deliveries "My agent" --json
a2a-workbench push listen "My agent"            # follow deliveries while `serve` runs
```

## Agent-calling mode (the Assistant)

The Assistant is an orchestrator LLM acting as an A2A client agent. Each agent you enable becomes one tool built only from its card (description, skills, examples, media types); the tool's inputs are exactly the A2A `Message` / `SendMessageConfiguration` fields. Before anything is sent, calls that break the protocol are rejected and shown: a `context_id` the agent never returned (§3.4.1), an unknown or finished `task_id` (follow-ups go in the same context with `reference_task_ids`), mismatched ids (§3.4.3), or parts the agent's input modes do not accept.

Every call is an ordinary conversation you can open in Chat, with full Inspect, faults and resubscribe, so you see exactly what the orchestrator sent. Streams that drop are resubscribed (§3.5.2), artifacts are the result (§3.7, with a warning when an agent returns output only in messages), and `auth_required` pauses the chat for you to sign in (§7.6.2) while the task is watched.

How results reach you is your choice (A2A leaves presentation to the client):

- **Assistant rewrites**: agents answer the Assistant and it answers you; each agent's raw output stays in its step.
- **Agents speak directly**: agents' output and questions come to you verbatim, your reply to a question goes straight to that agent, and the Assistant's context records what you saw.

Keys are managed on the **Settings** page (sidebar ⚙): one card per provider showing whether a key is saved or comes from the environment (never the key itself), with presets for OpenAI-compatible servers. **Inspect** on an Assistant chat shows every raw HTTP call made to the LLM provider (request and response bodies, headers with keys masked); each reply links to the call that produced it. Chats, conversations and agents can be deleted from the UI (`a2a-workbench chats list|calls|delete` on the CLI).

```bash
A2AW_LLM_API_KEY=… a2a-workbench providers set anthropic       # or set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
a2a-workbench providers set openai --base-url http://localhost:11434/v1   # Ollama, vLLM, LM Studio…
a2a-workbench assist "Book the cheapest flight to SFO" --agents "Travel agent" --json      # NDJSON steps
a2a-workbench assist "ask" --agents "Zoo agent" --response-mode pass-through
a2a-workbench assist "B" --session <id>                       # answer the agent's question
a2a-workbench chats calls <id> --json                         # raw LLM requests and responses (keys masked)
```

## Integrate

The Integrate tab (also `a2a-workbench integrate <agent> --target sdk|adk|langgraph|openai|claude` and the MCP `integration_guide` tool) generates client code from the agent's card. The plain-SDK code resolves the card, authenticates with the card's own schemes (secrets from environment variables), streams when declared, keeps `context_id` and `task_id`, continues `input_required` tasks, references finished tasks in follow-ups, resubscribes after a dropped stream, returns artifacts and raises `AuthRequired` for `auth_required`; every rule is commented with its spec section, and CI runs it against the reference agent. The framework versions wrap the same function as a tool (or use ADK's `RemoteA2aAgent`). A readiness list separates spec issues (missing REQUIRED skill fields) from advice (no examples, no media types, an extended card declared but not configured, …).

## Development

```bash
git config core.hooksPath .githooks
scripts/dev.sh                     # zoo agent :9999, API :8484, Vite :5173
uv run a2a-workbench fixtures --llm --port 9897   # scripted test LLM (OpenAI-compatible) for the Assistant
cd server && uv run pytest         # backend tests
cd web && pnpm test                # frontend tests
scripts/build.sh --no-wheel && (cd web && pnpm e2e)   # end-to-end
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE)
