# Testing A2A agents with A2A Workbench — guide for AI agents

A2A Workbench talks to A2A agents only through the official `a2a-sdk`. Use it
from a shell (CLI, JSON output) or as an MCP server. Both share one state
directory (`~/.a2a-workbench`, override with `A2AW_HOME`), so an agent
registered in one surface is visible in the other and in the web UI.

## Use it from Claude Code (MCP)

```bash
claude mcp add a2a-workbench -- uvx a2a-workbench mcp
```

Tools (all return JSON; failures come back as `{"error": {...}}`):

| Tool | Purpose |
|---|---|
| `fetch_card(target, extended=false)` | Fetch and verify the agent card (or the extended card plus differences) |
| `send_message(agent, text, …, conversation_id?, faults?)` | Send a message and wait; returns `conversation_id`, `events`, `final_state`, `error` |
| `get_task`, `list_tasks`, `cancel_task`, `subscribe_task` | The A2A task methods |
| `resubscribe(conversation_id)`, `check_status(conversation_id)` | Recover after a lost connection; the last event is `recovered` with a gap analysis |
| `list_exchanges(conversation_id)`, `get_exchange(exchange_id)` | Exact wire traffic (secrets redacted) |
| `list_agents`, `add_agent`, `fault_presets` | Registry and fault presets |
| `auth_status(agent)` | Security schemes, requirement alternatives, which credentials are stored (masked) |
| `set_credential(agent, scheme, api_key? / username+password? / token? / access_token? / cert_pem+key_pem?)` | Store a credential |
| `sign_in(agent, scheme, client_id, client_secret?, scopes?)` | OAuth client credentials or password; for device code it returns `user_code` + `verification_uri`, then `poll_sign_in(flow_id)` |
| `sign_out(agent, scheme)`, `auth_probe(agent)` | Remove a credential; check the agent enforces its declared auth |
| `assist(goal, agents?, provider, model?, response_mode?, session_id?)` | Run an orchestrator LLM that calls the agents as an A2A client agent; returns `steps` (tool_call, rejected_call, tool_result with `conversation_id` and ids, agent_output, paused, limit, error, done), `status` and `final_text` |
| `assistant_providers()` | Which LLM providers have a key (masked) |
| `integration_guide(agent, target?)` | Code for calling the agent from the plain SDK, ADK, LangGraph, OpenAI Agents or Claude Agent SDK, with guidance and readiness findings |

## Use it from a shell

```bash
a2a-workbench card http://localhost:9999 --json
a2a-workbench send http://localhost:9999 "hello" --json        # NDJSON, one event per line
a2a-workbench send "My agent" "continue" --context-id <ctx> --json
a2a-workbench tasks list "My agent" --status working --all --json
a2a-workbench tasks subscribe "My agent" <task-id> --json
a2a-workbench send "My agent" "long job" --faults flaky_stream --json
a2a-workbench faults presets --json
a2a-workbench auth status "My agent" --json
A2AW_TOKEN="$TOKEN" a2a-workbench auth set "My agent" bearer
A2AW_CLIENT_SECRET="$SECRET" a2a-workbench auth login "My agent" oauth --client-id "$ID" --scope read --json
a2a-workbench auth login "My agent" oauthDevice --client-id "$ID"   # prints a code to enter
a2a-workbench auth probe "My agent" --json
```

Agent-calling mode and integration code:

```bash
a2a-workbench assist "what can you do?" --agents "My agent" --provider anthropic --json
a2a-workbench assist "B" --session <id> --json        # continue, or answer an agent's question
a2a-workbench integrate "My agent" --target langgraph > call_my_agent.py
```

`assist` exits `0` when done or waiting for the user, `1` when a limit was hit
and `4` when an agent needs sign-in or no provider key is set.

Browser sign-in flows (authorization code, implicit, OpenID Connect) need a
person: ask the user to sign in from the web UI or with `a2a-workbench auth
login`, or to give you an access token for `set_credential`.

Exit codes: `0` ok · `1` checks failed · `2` usage error · `3` connection error
· `4` auth error · `5` protocol error (an A2A or HTTP error from the agent) ·
`6` internal error. Errors under `--json` print `{"error": {"category",
"message", "code"?, "reason"?, "http_status"?, "grpc_status"?}}`.

## Event shapes

Every timeline event is
`{"conversation_id", "seq", "kind", "ts", "task_id", "context_id", "exchange_id", "data"}`:

| kind | data |
|---|---|
| `user_message` | `message` (A2A Message JSON as sent), `options` |
| `task` | `task` (A2A Task JSON), `state` |
| `status` | `state`, `status` (TaskStatus JSON), `metadata` |
| `artifact` | `artifact` (the chunk), `append`, `last_chunk`, `assembled` (artifact so far) |
| `message` | `message` (agent Message JSON) |
| `error` | `category`, `message`, and `code`/`reason`/`http_status`/`grpc_status` when known |
| `connection_lost` | the error fields plus `task_id` and `last_state` |
| `recovered` | `method`, `snapshot_first`, `first_event`, `state_before`, `state_after`, `missed_states`, `missed_artifacts`, `duplicate_events`, `terminal` |

States are lowercase A2A task states: `submitted`, `working`, `input_required`,
`auth_required`, `completed`, `failed`, `canceled`, `rejected`.

## A good test loop for an agent you are building

1. `fetch_card` and check `signature_status`, the interfaces and the skills.
2. `send_message` with each skill's example; check `final_state` and the artifacts.
3. If the task needs input, send again with the same `conversation_id`.
4. Inspect `list_exchanges` / `get_exchange` when a reply looks wrong; the raw
   frames show exactly what the agent sent.
5. Resilience: `send_message(..., faults="flaky_stream")` on a long task, then
   `resubscribe(conversation_id)`. A compliant agent returns the current Task
   first (`snapshot_first: true`), sends nothing twice (`duplicate_events: 0`)
   and finishes (`terminal: true`).
6. Authentication: if a call fails with category `auth`, read `auth_status`,
   sign in, retry; then `auth_probe` to confirm the agent rejects anonymous
   and wrong credentials.
7. Agent callers: `assist` with your agent enabled shows how an orchestrator
   uses it; `rejected_call` steps and §3.7 warnings point at card or behaviour
   gaps, and `integration_guide` lists readiness advice.
8. Try every binding the card lists (switch with the web UI connection menu,
   or `send --interface <url>`).
