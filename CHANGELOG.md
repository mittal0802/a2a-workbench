# Changelog

All notable changes to A2A Workbench. Versions follow [Semantic Versioning](https://semver.org): after 1.0, the CLI (commands, flags, exit codes), the report JSON schema, the REST API under `/api` and the MCP tools only change incompatibly in a new major version.

## 1.0.0

First public release.

- **Connect** any A2A agent by URL: the agent card is fetched and its JWS signature verified; choose JSON-RPC, HTTP+JSON or gRPC, and protocol 1.0 or 0.3. Extended cards, with a diff against the public card.
- **Chat** with every part type (text, files, URLs, JSON data) and every message option; live streaming, `input_required` answers, stopping tasks, conversation history and a full Inspect view of every request and event with secrets redacted.
- **Tasks**: get, list with every filter and pagination, subscribe and cancel.
- **Fault injection** beneath the SDK (dropped streams, latency, resets) with presets, and guided recovery through resubscribe.
- **Security**: every scheme the spec defines (API key, HTTP Basic and Bearer, OAuth 2.0 flows, OpenID Connect, mutual TLS), credentials kept in an encrypted vault, and checks that the agent enforces what its card declares.
- **Push notifications**: create, get, list and delete push configs, and a built-in webhook receiver that validates every delivery; deliveries show in the chat and a Notifications inbox.
- **Assistant**: an LLM (Anthropic, OpenAI or compatible, Gemini; your own key) calls your agents as tools the way the spec defines a client agent.
- **Integrate**: copy-ready client code for the plain SDK, Google ADK, LangGraph, the OpenAI Agents SDK and the Claude Agent SDK.
- **Health checks**: 45 checks across discovery, transports, messaging, tasks, streaming, push, security, extensions, error codes and resilience, each citing its spec section, with a score, evidence, fixes and JSON/HTML reports; passive checks on live traffic.
- **Every surface**: web UI, a CLI with `--json` output and stable exit codes (CI-ready `check`), and an MCP server for AI agents.
- **Operations**: SQLite by default or Postgres (`a2a-workbench[postgres]`), automatic schema migrations that upgrade pre-1.0 databases in place, a non-root Docker image for amd64 and arm64, and a Docker Compose example.
