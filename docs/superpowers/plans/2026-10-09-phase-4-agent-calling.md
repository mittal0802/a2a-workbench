# Phase 4 — Agent-calling mode (Assistant) and Integrate: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An orchestrator LLM (Anthropic, OpenAI or compatible, Gemini; user's own key) calls registered A2A agents exactly the way the A2A specification defines a client agent, with Rewrite and Pass-through response modes, in every surface (web, CLI, MCP); plus an Integrate tab that generates spec-following code for calling an agent from the plain `a2a-sdk`, Google ADK, LangGraph/LangChain, the OpenAI Agents SDK and the Claude Agent SDK, with readiness advice.

**Architecture:** `core/assistant/` holds a provider-neutral chat model (`ChatMessage`, `ToolSpec`, `ToolCall`, `LLMReply`), one adapter per provider built on the provider's official Python SDK, a tool builder that derives one tool per agent strictly from the card, a call validator enforcing the §5.6 rules (server-issued `context_id`, non-terminal `task_id`, declared input modes), an executor that runs each tool call as an ordinary Workbench conversation (`origin="assistant"`) through `ConversationService`, and a session service with the run loop, limits, response modes, pause/resume for `input_required`/`auth_required`, persisted steps and live events on the bus. `core/integrate/` renders code templates and readiness findings from a card. API, CLI and MCP are thin layers; the web gets an Assistant page and an Integrate tab.

**Tech Stack:** Python 3.12, a2a-sdk 1.2.2, `anthropic`, `openai`, `google-genai`, FastAPI, SQLAlchemy, Typer, MCP 2.x; React 19, TanStack Query, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-07-a2a-workbench-design.md` §5.6, §5.6.1, §12 Phase 4. A2A text used for citations: A2A specification §1.2, §3.2.2, §3.3.4, §3.4, §3.5, §3.7, §7.3, §7.6, §8.3.2 and the "Life of a Task" guide.

## Global Constraints

- Phase 1–3 constraints apply (official SDK only for A2A, secrets only through the vault and never logged, docstrings describe the function, every feature in web + CLI + MCP with tests, no AI attribution in commits).
- Tool descriptions and inputs come only from A2A card / `Message` / `SendMessageConfiguration` fields. No skill selector is sent (A2A `Message` has no skill field).
- The orchestrator never fabricates protocol state: a `context_id` must have been returned by that agent in this session; a `task_id` must be known and non-terminal; follow-ups to terminal tasks use `reference_task_ids` in the same context.
- Results are artifacts (§3.7); a completed task that carries output only in messages is flagged with a §3.7 SHOULD warning on the step.
- `auth_required` is delegated to the human (§7.6.2); while paused the task is observed by polling `GetTask`.
- Provider keys are stored encrypted with the existing `Vault`; environment variables `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY` are used when no key is stored. Keys never appear in steps, logs or API responses.
- Response mode is a user setting (spec §5.6): `rewrite` (default) or `pass_through`.
- Limits: `max_steps=12` LLM turns per user message, `call_timeout_s=120`, `run_timeout_s=600`, `token_budget=200_000` (input+output tokens reported by the provider).

## Review Focus

1. **Orchestrator invents a `context_id` or reuses a terminal `task_id`:** the tool call is rejected before any A2A traffic, the LLM gets an explanation, and the step shows "rejected call" with the rule. *Test:* Task 2 `test_rejects_unknown_context_id`, `test_terminal_task_needs_a_follow_up_with_references`.
2. **Connection drops during an assistant call:** the executor resubscribes once (§3.5.2) and the LLM gets the final state, not a transport error. *Test:* Task 3 `test_dropped_stream_is_resubscribed_once`.
3. **Pass-through `input_required`:** the agent's question reaches the user verbatim, the run pauses, the user's reply goes to the agent on the same task without the LLM, and the LLM's context records both as already shown. *Test:* Task 4 `test_pass_through_question_goes_to_user_and_reply_to_agent`.
4. **Runaway loop:** an LLM that keeps calling tools stops at `max_steps` with a `limit` step; the token budget is enforced the same way. *Test:* Task 4 `test_step_limit_stops_the_run`, `test_token_budget_stops_the_run`.
5. **Provider key never leaks:** stored key absent from API responses, steps, exchange records and CLI/MCP output. *Test:* Task 1 `test_provider_key_is_masked_everywhere`, Task 5 `test_session_api_never_returns_the_key`.

---

### Task 1: LLM adapters, provider keys and the scripted test LLM

**Files:**
- Create: `server/a2a_workbench/core/assistant/__init__.py`, `core/assistant/llm.py` (neutral types, `LLMAdapter` protocol, `adapter_for`), `core/assistant/providers/anthropic.py`, `providers/openai.py`, `providers/gemini.py`, `core/assistant/keys.py` (`ProviderKeyStore`), `fixtures/llm.py` (`ScriptedLLM` policy, `ScriptedAdapter`, `FakeOpenAIServer`)
- Modify: `core/store/models.py` (`ProviderKey`), `core/workbench.py` (`self.provider_keys`), `pyproject.toml` (deps `anthropic`, `openai`, `google-genai`)
- Test: `tests/core/assistant/test_llm_adapters.py`, `test_provider_keys.py`, `tests/fixtures/test_fake_llm.py`

**Interfaces (produces):**
```python
class ToolSpec(BaseModel): name: str; description: str; input_schema: dict[str, Any]
class ToolCall(BaseModel): id: str; name: str; arguments: dict[str, Any]
class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: list[ToolCall] = []      # assistant only
    tool_call_id: str | None = None      # tool only
    is_error: bool = False               # tool only
class Usage(BaseModel): input_tokens: int = 0; output_tokens: int = 0
class LLMReply(BaseModel): text: str; tool_calls: list[ToolCall]; usage: Usage; stop_reason: str
class LLMAdapter(Protocol):
    async def complete(self, system: str, messages: list[ChatMessage], tools: list[ToolSpec]) -> LLMReply: ...
def adapter_for(provider: Literal["anthropic","openai","gemini"], model: str, api_key: str, base_url: str | None = None) -> LLMAdapter
class ProviderKeyStore:
    async def put(self, provider: str, api_key: str, base_url: str | None = None) -> ProviderKeyInfo
    async def get(self, provider: str) -> tuple[str, str | None] | None   # (key, base_url), env fallback
    async def list(self) -> list[ProviderKeyInfo]                           # masked preview, source "stored"|"env"
    async def delete(self, provider: str) -> None
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-5.1", "gemini": "gemini-3-pro"}
class LLMError(Exception): category: Literal["auth","rate_limit","provider"]; message: str
```

- [ ] **Step 1: Failing tests.** Adapters: with `respx` mocking each provider's HTTP endpoint, assert the request translation (system prompt placement, tool schema format, tool results as `tool_result` blocks / `role: tool` messages / `functionResponse` parts, tool-call ids round trip) and the reply parsing (text, tool calls with parsed JSON arguments, usage, stop reason). `test_openai_compatible_base_url` sends to the given `base_url`. `test_auth_error_is_llm_error` maps 401 to `LLMError(category="auth")` with a message that never contains the key. Keys: `test_put_get_list_delete`, `test_env_fallback` (`monkeypatch.setenv("ANTHROPIC_API_KEY", …)` → `list()` shows source `env`), `test_provider_key_is_masked_everywhere` (key absent from `list()` dump and from respx-recorded logs of `caplog`). Fake LLM: `FakeOpenAIServer` answers `/v1/chat/completions` according to `ScriptedLLM` (policy below) and the OpenAI adapter talks to it end to end.
- [ ] **Step 2: Run, expect FAIL** (`uv run pytest tests/core/assistant tests/fixtures/test_fake_llm.py -q` → import errors).
- [ ] **Step 3: Implement.** Adapters use `anthropic.AsyncAnthropic(api_key=…, max_retries=1)`, `openai.AsyncOpenAI(api_key=…, base_url=…)` (Chat Completions with `tools=[{"type":"function","function":{…}}]`), `google.genai.Client(api_key=…).aio.models.generate_content` with `FunctionDeclaration`s. `ScriptedLLM` policy (deterministic, for tests and e2e): last message is a user text → call the first tool with `{"message": <text>}`; last message is a tool result whose JSON has `state == "input_required"` → if the goal contains "ask me" answer with text `Question from the agent: <question>`, otherwise call the same tool with the same `task_id`/`context_id` and `{"message": "B"}`; tool result terminal → text `Done: <first artifact text or message>`; a goal containing "loop forever" always calls the first tool (for limit tests).
- [ ] **Step 4: Run, expect PASS**, then the full server suite.
- [ ] **Step 5: Commit** `feat(assistant): provider-neutral LLM adapters (Anthropic, OpenAI-compatible, Gemini) and encrypted provider keys`.

### Task 2: Tool builder and call validation (the §5.6 rules)

**Files:** Create `core/assistant/tools.py`; Test `tests/core/assistant/test_tools.py`.

**Interfaces:**
```python
class AgentTool(BaseModel): spec: ToolSpec; agent_id: str
def build_tools(agents: list[AgentOut]) -> list[AgentTool]   # call_<slug>, unique; plus get_task, cancel_task helper specs
def describe_agent(card: AgentCard) -> str                   # only card fields (name, description, default modes, skills: id/name/description/tags/examples/modes)
class SessionIds:  # per session, per agent: contexts and tasks the agent returned
    def record(self, agent_id: str, context_id: str | None, task_id: str | None, state: str | None) -> None
    def context_known(self, agent_id: str, context_id: str) -> bool
    def task_state(self, agent_id: str, task_id: str) -> str | None
class CallRejected(Exception): rule: str; spec_ref: str; message: str
def validate_call(card: AgentCard, agent_id: str, args: dict[str, Any], ids: SessionIds) -> None
```
Rules (each raises `CallRejected` with the rule and spec reference): `context_id` not returned by this agent earlier (§3.4.1 SHOULD NOT generate); unknown `task_id` (§3.4.2 MUST reference existing task); terminal `task_id` (Life of a Task — Task Immutability: "send a follow-up in the same context_id with reference_task_ids"); `task_id` whose recorded context differs from the given `context_id` (§3.4.3 MUST reject mismatching ids); `data` given but neither the card's `defaultInputModes` nor any skill's `inputModes` includes `application/json` (or a non-MIME `data` token); `file_urls` given but no file-capable mode declared; `reference_task_ids` with ids not returned by this agent.

- [ ] **Step 1: Failing tests:** `test_tool_description_uses_only_card_fields` (zoo card → description contains each skill id/name/examples, no keys outside the card), `test_tool_names_are_unique_slugs`, `test_rejects_unknown_context_id`, `test_rejects_unknown_task_id`, `test_terminal_task_needs_a_follow_up_with_references`, `test_mismatched_context_and_task_rejected`, `test_data_part_needs_a_json_input_mode`, `test_valid_continuation_passes`.
- [ ] **Step 2: FAIL.** **Step 3: Implement.** **Step 4: PASS + suite.**
- [ ] **Step 5: Commit** `feat(assistant): tools built only from the agent card; reject calls that break A2A context and task rules`.

### Task 3: Executor — one tool call as one A2A conversation

**Files:** Create `core/assistant/executor.py`; Modify `core/conversations/options.py` (`inherit_ids: bool = True`), `core/conversations/service.py` (when `inherit_ids` is false use only the ids given in options); Modify `fixtures/zoo.py` (behaviour `note`: completes with a status message and no artifact); Test `tests/core/assistant/test_executor.py`.

**Interfaces:**
```python
class ToolResult(BaseModel):
    agent: str; conversation_id: str; kind: Literal["message","task","error"]
    context_id: str | None; task_id: str | None; state: str | None
    question: str | None          # agent text when input_required / auth_required
    messages: list[str]           # agent message / status message texts, in order
    artifacts: list[dict[str, Any]]  # {"name","parts":[{"kind","text"|"data"|"file"}]}
    warnings: list[str]           # e.g. §3.7 output-in-messages
    error: dict[str, Any] | None
    def for_llm(self, shown_to_user: bool) -> str   # JSON text given to the LLM
class AgentCallExecutor:
    def __init__(self, wb: Workbench) -> None
    async def call(self, agent_id: str, args: dict[str, Any], *, conversation_id: str | None, timeout_s: float,
                   on_event: Callable[[TimelineEvent], Awaitable[None]] | None = None) -> ToolResult
    async def get_task(self, agent_id: str, task_id: str) -> ToolResult
    async def cancel_task(self, agent_id: str, task_id: str) -> ToolResult
```
Behaviour: creates the conversation (`origin="assistant"`) when none is given; sends with `inherit_ids=False`, the call's `context_id`/`task_id`/`reference_task_ids`/`accepted_output_modes`, `stream = card.capabilities.streaming`; on a `connection_lost` event calls `ConversationService.resubscribe` once and uses its events; on timeout returns `state` so far plus warning "still running; call get_task". §3.7 warning: completed task, no artifacts, non-empty messages.

- [ ] **Step 1: Failing tests:** `test_new_call_creates_assistant_conversation`, `test_continuation_uses_exact_ids` (ask → answer B with task_id → completed; the stored user_message shows exactly the given ids), `test_inherit_ids_false_does_not_attach_open_task`, `test_message_reply_has_context_and_no_task`, `test_output_only_in_messages_gets_section_3_7_warning` (zoo `note`), `test_dropped_stream_is_resubscribed_once` (flaky_stream preset), `test_timeout_returns_running_state`, `test_auth_error_result`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(assistant): run each tool call as an A2A conversation with exact ids, resubscribe and §3.7 checks`.

### Task 4: Sessions and the run loop (limits, response modes, pauses)

**Files:** Create `core/assistant/service.py`, `core/assistant/prompt.py` (system prompt text); Modify `core/store/models.py` (`AssistantSession`, `AssistantStep`), `core/workbench.py` (`self.assistant`); Test `tests/core/assistant/test_sessions.py`.

**Interfaces:**
```python
ResponseMode = Literal["rewrite", "pass_through"]
class Limits(BaseModel): max_steps: int = 12; call_timeout_s: float = 120; run_timeout_s: float = 600; token_budget: int = 200_000
class SessionIn(BaseModel): provider: str; model: str | None = None; response_mode: ResponseMode = "rewrite"; agent_ids: list[str]; limits: Limits = Limits(); title: str | None = None
class Step(BaseModel):
    session_id: str; seq: int; ts: datetime
    kind: Literal["user","assistant","tool_call","rejected_call","tool_result","agent_output","paused","resumed","limit","error","done"]
    data: dict[str, Any]
class SessionOut(BaseModel): id, title, provider, model, response_mode, agent_ids, limits, status: Literal["idle","running","awaiting_user","awaiting_sign_in","stopped"], created_at, updated_at
class AssistantService:
    async def create(self, body: SessionIn) -> SessionOut
    async def list(self) -> list[SessionOut]; async def get(self, sid) -> SessionOut; async def steps(self, sid, after_seq=0) -> list[Step]
    def send(self, sid: str, text: str) -> AsyncIterator[Step]     # one user turn; pass-through reply when awaiting_user
    def resume(self, sid: str) -> AsyncIterator[Step]              # after sign-in: GetTask, feed state to the LLM, continue
    async def stop(self, sid: str) -> None
    async def set_mode(self, sid: str, mode: ResponseMode) -> SessionOut
```
Loop: append user message; repeat up to `max_steps`: `adapter.complete(system, history, tools)`; record `assistant` step (text, usage); no tool calls → `done`; for each call: `tool_call` step → validate (`rejected_call` + error tool message on `CallRejected`) → execute → `tool_result` step (with `conversation_id`, ids, state, warnings, `answered_by` when the call answered an `input_required` question: `"assistant"`). Pass-through: each agent status message / artifact during the call is also emitted as an `agent_output` step (verbatim parts) and the LLM tool message says it was shown to the user. `input_required` in pass-through → `paused` step (`reason="input_required"`, agent question verbatim) and status `awaiting_user`; the next `send(text)` goes straight to the agent on that task (`answered_by="user"`), is appended to the LLM history as a user note ("The user answered <agent> directly: …") plus the tool result, then the loop continues. `auth_required` (either mode) → `paused` (`reason="auth_required"`, message, agent_id) and status `awaiting_sign_in`; a watcher polls `GetTask` every 3 s for up to `run_timeout_s` and calls `resume` when the state changes; `resume` can also be triggered by the user. Token budget and wall clock checked each turn → `limit` step. Steps persisted and published on bus topic `assistant:{id}`. Session transcript (neutral `ChatMessage`s) persisted for later turns. Provider key from `ProviderKeyStore`; missing → `error` step `{"category":"auth","message":"No API key for <provider>"}`.

- [ ] **Step 1: Failing tests** (with `ScriptedAdapter` and the zoo): `test_rewrite_mode_answers_question_itself` (ask → B → `Done: You chose: B`, `answered_by == "assistant"`), `test_rewrite_mode_can_ask_the_user` (goal "ask me" → done with question; next send continues the same task id), `test_pass_through_question_goes_to_user_and_reply_to_agent`, `test_pass_through_streams_agent_output_steps`, `test_rejected_call_is_reported_to_the_llm`, `test_step_limit_stops_the_run`, `test_token_budget_stops_the_run`, `test_auth_required_pauses_and_resumes_after_sign_in` (oauth zoo `hold`), `test_missing_provider_key_is_an_error_step`, `test_steps_are_persisted_and_published`, `test_stop_cancels_a_running_turn`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(assistant): sessions, run loop with limits, rewrite and pass-through modes, sign-in pauses`.

### Task 5: API, WebSocket, CLI and MCP for the Assistant

**Files:** Create `api/routes_assistant.py`; Modify `api/app.py`, `api/ws.py` (topic `assistant:{id}`), `cli/main.py` (`assist` command, `assist-keys` group → name `providers`), `mcp/server.py` (`assist`, `assistant_providers`); Tests `tests/api/test_assistant_api.py`, `tests/cli/test_assist_cli.py`, `tests/mcp/test_mcp_assist.py`.

API: `GET/PUT/DELETE /api/assistant/providers[/{provider}]` (`{api_key, base_url?}` in, masked info out), `POST /api/assistant/sessions`, `GET /api/assistant/sessions`, `GET /api/assistant/sessions/{id}` (session + steps), `POST /api/assistant/sessions/{id}/messages {text}` (202, runs in background), `POST …/resume`, `POST …/stop`, `PATCH …` (`response_mode`). CLI: `a2a-workbench assist "<goal>" --agents a,b --provider openai [--model] [--base-url] [--response-mode rewrite|pass-through] [--session ID] [--max-steps N] [--json]` (NDJSON steps; exit 0 done, 4 auth / sign-in pause, 2 usage, 1 limit reached); `a2a-workbench providers set|list|remove` (key from `--api-key -`/env, never echoed). MCP: `assist(goal, agents, provider, model?, base_url?, response_mode?, session_id?)` → `{session_id, status, steps, final_text}`; `assistant_providers()`. Tests drive the stack with `FakeOpenAIServer` (`--provider openai --base-url http://127.0.0.1:<port>/v1`, key `test`).

- [ ] **Step 1: Failing tests:** `test_session_lifecycle_over_api_and_ws`, `test_session_api_never_returns_the_key`, `test_cli_assist_ndjson_and_exit_codes`, `test_cli_providers_set_list_remove`, `test_mcp_assist_returns_steps_and_final_text`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(assistant): API, WebSocket, CLI assist and providers, MCP assist`.

### Task 6: Web Assistant page

**Files:** Create `web/src/features/assistant/{AssistantPage,StepCard,AgentsPanel,ProviderSettings}.tsx` + tests; Modify `web/src/App.tsx` (route `/assistant/:sessionId?`), `components/Sidebar.tsx` (Assistant nav), `lib/api.ts`, `lib/types.ts`.

Per the mockup: header with model button (opens ProviderSettings: provider, model, base URL, key field — key shown masked once saved), response-mode switch ("Assistant rewrites" / "Agents speak directly"), thread of user messages, assistant text and collapsible step cards ("Asked **Agent** …", state pill, the exact message sent with ids, agent output verbatim, warnings, rejected-call rule, "Open this conversation →" link to the agent chat with that conversation), pause cards (question with reply box in pass-through; Sign in button → agent Security tab; Continue), right panel "Agents it can use" with toggles, composer "Ask the assistant…" and "Using N agents".

- [ ] **Step 1: Failing tests:** renders steps from fixtures; sends a message; mode switch PATCHes; pass-through pause shows the agent's verbatim question and sends the reply; auth pause links to Security and Continue calls resume; provider settings never render a stored key; live steps arrive over WS.
- [ ] **Step 2–4** (`pnpm vitest run`, `pnpm lint`). **Step 5: Commit** `feat(web): Assistant page with step timeline, response modes and agent toggles`.

### Task 7: Integrate core — code generation, guidance and readiness

**Files:** Create `core/integrate/__init__.py`, `core/integrate/templates.py`, `core/integrate/readiness.py`, `core/integrate/service.py`; Test `tests/core/integrate/test_snippets.py`, `test_readiness.py`.

**Interfaces:**
```python
Target = Literal["sdk", "adk", "langgraph", "openai", "claude"]
class Snippet(BaseModel): target: Target; language: str; install: str; code: str; env: dict[str, str]   # env var name -> meaning
class Finding(BaseModel): level: Literal["spec", "advice"]; code: str; message: str; path: str; spec_ref: str | None
class IntegrationGuide(BaseModel): agent_id: str; card_url: str; snippets: dict[Target, Snippet]; guidance: list[str]; readiness: list[Finding]
def render(card: AgentCard, card_url: str, target: Target) -> Snippet
def readiness(card: AgentCard) -> list[Finding]
class IntegrationService: async def guide(self, agent_id: str, *, live: bool = True) -> IntegrationGuide
```
Every snippet: resolves the card from `card_url` with `A2ACardResolver`; picks the interface by §8.3.2 through `ClientFactory`; authenticates per the card's first requirement alternative using env vars (`A2A_API_KEY`, `A2A_TOKEN`, `A2A_CLIENT_ID`/`A2A_CLIENT_SECRET` for client credentials against the card's token URL, …) sent through `ClientCallContext.service_parameters`; streams when `capabilities.streaming`; keeps `context_id`/`task_id`; continues `input_required` on the same task; follow-ups after terminal states with `reference_task_ids`; resubscribes on a dropped stream; returns artifacts as the result and raises `AuthRequired` for `auth_required`; each rule commented with its spec section. Framework snippets wrap the plain-SDK `call_agent` function as a tool (LangGraph `@tool`, OpenAI Agents `@function_tool`, Claude Agent SDK `@tool` + `create_sdk_mcp_server`) or use ADK `RemoteA2aAgent`. Readiness: `spec` findings for missing REQUIRED `AgentSkill` fields (`id`, `name`, `description`, `tags`) citing `a2a.proto AgentSkill`; `advice` for skills without `examples`, no input/output modes anywhere, description over 600 characters, empty skill list, and (live) `ExtendedAgentCardNotConfiguredError` while `capabilities.extendedAgentCard` is true (§3.3.4).

- [ ] **Step 1: Failing tests:** `test_sdk_snippet_runs_against_the_zoo` (write the rendered code to tmp, run with `sys.executable` and env `A2A_MESSAGE=ask`, `A2A_REPLY=B` against the zoo; stdout contains `You chose: B`), `test_sdk_snippet_authenticates_with_bearer_from_env` (bearer zoo), `test_every_snippet_parses` (`ast.parse` for all targets and auth modes), `test_snippets_never_contain_secrets`, `test_readiness_spec_and_advice_findings`, `test_live_extended_card_not_configured_is_advice`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(integrate): spec-following client code for the SDK, ADK, LangGraph, OpenAI and Claude agent SDKs, plus readiness`.

### Task 8: Integrate surfaces

**Files:** Modify `api/routes_agents.py` (`GET /api/agents/{id}/integration`), `cli/main.py` (`integrate <agent> --target … [--json]`), `mcp/server.py` (`integration_guide(agent, target?)`); Create `web/src/features/integrate/IntegrateView.tsx` + test; Modify `features/agent/AgentPage.tsx` (tab "Integrate"). Tests: API, CLI, MCP, web.

Web: target switcher (Plain SDK, Google ADK, LangGraph, OpenAI Agents, Claude Agent SDK), install line, code block with Copy and Download, env var table, "Calling it from another agent" guidance (both response modes explained; A2A leaves presentation to the client), readiness list (spec issues vs advice, each with path and reference).

- [ ] **Step 1: Failing tests:** `test_integration_endpoint`, `test_cli_integrate_prints_code_and_json`, `test_mcp_integration_guide`, web `IntegrateView` switches targets and copies code.
- [ ] **Step 2–4.** **Step 5: Commit** `feat: Integrate tab, integrate CLI command and integration_guide MCP tool`.

### Task 9: E2E and docs

E2E (`web/e2e/assistant.spec.ts`): Playwright web server list gains `FakeOpenAIServer` (`uv run a2a-workbench fixtures --llm --port 9897`); configure provider OpenAI-compatible with base URL, ask "ask", see the step card "Asked Zoo agent", final "Done: You chose: B", open the conversation; switch to pass-through and see the agent's question verbatim and reply; Integrate tab copies the SDK snippet. Docs: README Assistant and Integrate sections, `docs/agents.md` (`assist`, `integration_guide`), spec §5.6 note on the non-streaming LLM ruling if taken, `docs/upstream-gaps.md` for any SDK gap met.

- [ ] Steps: write e2e (fails), add `--llm` to `fixtures`, make it pass, docs, commit `test(e2e): assistant in both response modes and the Integrate tab; docs`.

## Self-Review

Spec §5.6: adapters (T1), discovery/interface/credentials via existing `open_client` (T3), tool per agent from card only (T2), inputs = Message/SendMessageConfiguration fields (T2), no skill selector (T2), delivery streaming/blocking + resubscribe (T3), results/§3.7 (T3), multi-turn and terminal follow-ups (T2/T4), auth_required delegation + observation (T4), extensions only as enabled — executor sends `extensions` only from the session's per-agent enabled list (T3; default none), response modes (T4/T6), limits (T4), visibility via conversations `origin=assistant` (T3/T6), surfaces (T5/T6). §5.6.1: code for five targets, presentation guidance, readiness, surfaces (T7/T8). Review Focus items each have a named test.
