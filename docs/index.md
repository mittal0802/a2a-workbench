# A2A Workbench

Debug, test and conformance-check any [A2A](https://a2a-protocol.org) agent: a web UI, a CLI built for scripts and CI, and an MCP server for AI agents. All A2A traffic goes through the official [`a2a-sdk`](https://github.com/a2aproject/a2a-python), so what you see is what a real client sees.

| | |
|---|---|
| **Connect** | any agent by URL; card fetched and its signature verified; JSON-RPC, HTTP+JSON or gRPC; protocol 1.0 or 0.3 |
| **Chat** | every part type and message option, live streaming, `input_required` answers, stop tasks |
| **Inspect** | every request, response and streamed event on the wire, secrets redacted |
| **Tasks** | get, list with every filter, subscribe, cancel |
| **Faults** | drop streams, add latency, refuse connections, and check recovery |
| **Security** | every scheme the spec defines, an encrypted vault, and an enforcement probe |
| **Push** | a built-in webhook receiver that validates every notification |
| **Health checks** | 45 spec checks with a score, evidence, fixes and reports, CI-ready |
| **Assistant** | an LLM calls your agents as tools, the way a client agent would |
| **Integrate** | copy-ready client code for the SDK, ADK, LangGraph, OpenAI Agents SDK, Claude Agent SDK |

Start with [Install](install.md) and the [Quick start](quickstart.md).
