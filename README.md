# A2A Workbench

Debug, test and conformance-check any [A2A](https://a2a-protocol.org) agent: a friendly web UI, a CLI built for scripts, CI and AI agents, and an MCP server, all speaking A2A exclusively through the official [`a2a-sdk`](https://github.com/a2aproject/a2a-python).

- **Connect** any agent by URL: the agent card is fetched, its JWS signature verified, and you choose the interface (JSON-RPC, REST or gRPC) and protocol version (1.0, or 0.3 through the SDK's compat layer).
- **Chat** with it using every part type (text, files, URLs, JSON data) and every `SendMessageConfiguration` option, stream replies live, answer `input_required` questions, stop tasks.
- **Tasks**: get, list (every filter, pagination), subscribe and cancel.
- **Break the connection on purpose**: inject faults beneath the SDK (dropped streams, latency, resets) and check that resubscribe gets you back in sync.
- **Sign in** with every security scheme the spec defines, and check the agent actually enforces it.
- **Inspect** every request, response and server-sent event that went over the wire, with secrets redacted; copy or export it as JSON.
- **Script it**: every action is also a CLI command with `--json` / NDJSON output and stable exit codes, and an MCP tool for AI agents.

> Status: Phase 3 of 7 (security). See the [design spec](docs/superpowers/specs/2026-10-07-a2a-workbench-design.md) for the roadmap: agent-calling mode (an LLM orchestrator calling your agents the way the A2A spec defines) and integration guides, push notifications, health checks, and the hosted instance.

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

## Development

```bash
git config core.hooksPath .githooks
scripts/dev.sh                     # zoo agent :9999, API :8484, Vite :5173
cd server && uv run pytest         # backend tests
cd web && pnpm test                # frontend tests
scripts/build.sh --no-wheel && (cd web && pnpm e2e)   # end-to-end
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE)
