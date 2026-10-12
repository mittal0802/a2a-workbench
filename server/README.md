# A2A Workbench

Debug, test and conformance-check any [A2A](https://a2a-protocol.org) agent: a web UI, a CLI built for scripts and CI, and an MCP server for AI agents, all speaking A2A exclusively through the official [`a2a-sdk`](https://github.com/a2aproject/a2a-python).

- **Connect** any agent by URL: the card is fetched and its signature verified; pick JSON-RPC, REST or gRPC, protocol 1.0 or 0.3.
- **Chat** with every part type and message option, stream replies, answer `input_required`, stop tasks.
- **Tasks**: get, list with every filter, subscribe, cancel.
- **Break the connection on purpose** with fault injection and check that resubscribe recovers.
- **Sign in** with every security scheme the spec defines, and check the agent enforces it.
- **Push notifications** through a built-in webhook receiver that validates every delivery.
- **Health checks**: score an agent against the A2A spec, with evidence, fixes and JSON/HTML reports, from the UI, the CLI (CI exit codes) or MCP.
- **Assistant** and **Integrate**: let an LLM call your agent as a tool, and copy client code for the SDK, ADK, LangGraph, the OpenAI Agents SDK or the Claude Agent SDK.

## Install

```bash
pipx install a2a-workbench          # or: uv tool install a2a-workbench
a2a-workbench serve --open          # web UI on http://127.0.0.1:8484
```

Or with Docker:

```bash
docker run -p 127.0.0.1:8484:8484 -v a2aw:/data ghcr.io/mittal0802/a2a-workbench
```

Postgres instead of the default SQLite: `pipx install 'a2a-workbench[postgres]'` and set `A2AW_DATABASE_URL=postgresql+asyncpg://user:password@host/db`.

## Check an agent from CI

```bash
a2a-workbench check https://agent.example.com --fail-on fail --format json --out report.json
```

Exit codes: `0` ok, `1` checks failed, `2` usage error, `3` connection error, `4` auth error, `5` protocol error, `6` internal error.

## Links

- Documentation: https://mittal0802.github.io/a2a-workbench/
- Source and issues: https://github.com/mittal0802/a2a-workbench
- Changelog: https://github.com/mittal0802/a2a-workbench/blob/main/CHANGELOG.md

Apache-2.0.
