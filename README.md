# A2A Workbench

Debug, test and conformance-check any [A2A](https://a2a-protocol.org) agent: a friendly web UI, a CLI built for scripts, CI and AI agents, and (soon) an MCP server, all speaking A2A exclusively through the official [`a2a-sdk`](https://github.com/a2aproject/a2a-python).

- **Connect** any agent by URL: the agent card is fetched, its JWS signature verified, and you choose the interface (JSON-RPC or REST; gRPC coming) and protocol version.
- **Chat** with it using every part type (text, files, URLs, JSON data) and every `SendMessageConfiguration` option, stream replies live, answer `input_required` questions, stop tasks.
- **Inspect** every request, response and server-sent event that went over the wire, with secrets redacted.
- **Script it**: every action is also a CLI command with `--json` / NDJSON output and stable exit codes.

> Status: Phase 1 of 7 (foundation, connect, chat). See the [design spec](docs/superpowers/specs/2026-10-07-a2a-workbench-design.md) for the full roadmap: all bindings and versions, failure injection and resubscribe testing, auth, push notifications, health checks, and an LLM assistant that calls your agents.

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
a2a-workbench send http://localhost:9999 "inspect" \
  --file report.pdf --data '{"n": 1}' --accept application/json \
  --history-length 5 --extension https://example.com/ext/x --metadata '{"k": "v"}'
```

Exit codes: `0` ok, `1` checks failed, `2` usage error, `3` connection error, `4` auth error, `5` protocol error, `6` internal error.

State lives in `~/.a2a-workbench/` (override with `A2AW_HOME`; database with `DATABASE_URL`).

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
