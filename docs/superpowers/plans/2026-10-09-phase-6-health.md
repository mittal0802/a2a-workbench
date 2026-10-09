# Phase 6 — Health checks: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A conformance engine that probes an A2A agent through the official SDK and reports, per spec requirement, whether it complies (MUST → fail, SHOULD → warn, undeclared feature → not_supported), with evidence exchanges, fix hints, a score and JSON/HTML reports; run from the web (Health tab, Health page), the CLI (`a2a-workbench check`, CI-friendly exit codes) and MCP (`run_health_check`, `list_findings`); passive checks on live traffic; and `broken-*` zoo agents proving every check detects its violation.

**Architecture:** `core/health/` holds the `Check` model (id, area A–L, title, spec_ref, level, applies(card), run(ctx) → Result, fix_hint), a registry, `RunContext` (agent, card, interface, auth, faults, a recording scope that collects evidence exchange ids, a scratch conversation for probe tasks, the tasks the run created), the runner (per interface, sequential, progress on bus `health-run:<id>`), scoring, report rendering (versioned JSON schema, self-contained HTML), persistence (`health_run`), and passive checks evaluated on recorded exchanges. Checks drive the agent only through `ConversationService`, `TaskService`, `PushService` and the card fetcher — i.e. the official SDK. Wire-level facts the SDK hides (JSON-RPC error codes, HTTP statuses, field presence) are read from the recorded exchange of the probe, never from hand-built requests.

**Tech Stack:** a2a-sdk 1.2.2, FastAPI, SQLAlchemy, Typer, MCP, React.

**Spec:** `docs/superpowers/specs/2026-10-07-a2a-workbench-design.md` §3 (rows A–L), §5.5, §5.9, §12 Phase 6. A2A: §3.1, §3.2, §3.3, §3.4, §3.5, §3.6, §3.7, §4.3, §5.1, §5.4, §7.4, §8, §13.

## Global Constraints

- Earlier constraints apply (official SDK only for A2A traffic, secrets masked, every surface, docstrings describe the function, no AI attribution).
- **Only what the spec says.** Each check cites its section; `level="must"` failures are `fail`, `level="should"` are `warn`. A feature the card does not declare yields `not_supported` (not counted). Workbench-side problems are `error` (shown separately, not counted).
- **No hand-built requests.** Probes that would need malformed JSON-RPC/HTTP (parse error, invalid request, unknown method) are out of scope: the SDK cannot send them and the project rule forbids building A2A traffic by hand. Ruling recorded; the error-mapping checks cover every A2A error the SDK can provoke.
- **Safety.** Probes create real tasks; destructive probes (cancel, delete push config) only touch tasks the run created. The UI warns before a run.
- **Score** = round(100 × (pass + 0.5 × warn) ÷ applicable), applicable = pass + warn + fail.
- **Report JSON** schema version `1`: `{schema, agent, card_url, interfaces, started_at, finished_at, score, counts, results:[{check_id, area, title, spec_ref, level, interface, status, expected, actual, fix_hint, exchange_ids, duration_ms}]}`. Golden test pins the shape.

## Check catalogue (initial)

| id | area | level | rule (A2A ref) |
|---|---|---|---|
| A1 card.reachable | A | must | Agent Card served at the well-known path (§8.1, §8.2) |
| A2 card.required_fields | A | must | REQUIRED AgentCard fields present (proto field_behavior) |
| A3 card.interfaces | A | must | each interface declares url, protocolBinding, protocolVersion (§8.3.1) |
| A4 card.skills_required | A | must | REQUIRED AgentSkill fields (id, name, description, tags) |
| A5 card.signature | A | must | declared signatures verify (§8.4.3); not_supported if unsigned |
| A6 card.caching | A | should | Cache-Control max-age and ETag on the card (§8.6.1) |
| A7 extended.capability | A | must | extendedAgentCard true → card or ExtendedAgentCardNotConfigured; false → UnsupportedOperation (§3.3.4) |
| B1 interface.answers | B | must | every declared interface answers an A2A call (§5.2 MUST declare supported protocols) |
| B2 interface.equivalent | B | must | same task/error results across bindings (§5.1) |
| B3 version.unsupported | B | must | unsupported `A2A-Version` → VersionNotSupportedError (§3.6.2) |
| C1 send.shape | C | must | SendMessage returns a Task or a Message (§3.1.1) |
| C2 send.blocking_state | C | must | blocking send returns a terminal or interrupted state (§3.2.2) |
| C3 context.generated | C | must | a generated contextId is included in the response (§3.4.1) |
| C4 task.unknown_continue | C | must | message with unknown taskId → TaskNotFoundError (§3.4.2) |
| C5 task.context_mismatch | C | must | mismatching contextId/taskId rejected (§3.4.3) |
| C6 task.terminal_message | C | must | message to a terminal task → UnsupportedOperationError (§3.1.1) |
| C7 history.zero | C | should | historyLength 0 omits history (§3.2.4) |
| E1 results.artifacts | E | should | results returned as artifacts, not only messages (§3.7) |
| F1 get.task | F | must | GetTask returns the task by id (§3.1.3) |
| F2 get.unknown | F | must | GetTask unknown id → TaskNotFoundError (§3.1.3) |
| F3 get.history_length | F | must | no more history than historyLength (§3.2.4) |
| F4 list.contains_and_filters | F | must | ListTasks returns the run's task; contextId filter honoured (§3.1.4, §13.1) |
| F5 list.next_page_token | F | must | nextPageToken always present, "" on the last page (§3.1.4) |
| F6 list.artifacts_omitted | F | must | without includeArtifacts the artifacts field is omitted (§3.1.4) |
| F7 list.order | F | must | sorted by status timestamp, newest first (§3.1.4) |
| F8 cancel.terminal | F | must | cancel a terminal task → TaskNotCancelableError (§3.1.5) |
| F9 cancel.unknown | F | must | cancel unknown id → TaskNotFoundError (§3.1.5) |
| G1 stream.capability | G | must | streaming false → UnsupportedOperationError for SendStreamingMessage (§3.3.4) |
| G2 stream.first_event | G | must | stream begins with Task or is exactly one Message (§3.1.2) |
| G3 stream.closes_on_terminal | G | must | stream closes after a terminal state (§3.1.2) |
| G4 subscribe.task_first | G | must | SubscribeToTask's first event is the Task (§3.1.6) |
| G5 subscribe.terminal | G | must | subscribe to a terminal task → UnsupportedOperationError (§3.1.6) |
| H1 push.capability | H | must | pushNotifications false → PushNotificationNotSupportedError (§3.3.4) |
| H2 push.crud | H | must | create/get/list/delete round trip (§3.1.7–§3.1.10) |
| H3 push.delete_idempotent | H | must | deleting twice has the same effect (§3.1.10) |
| H4 push.delivery_auth | H | must | deliveries carry the configured Authorization (§4.3.3) — only when a reachable webhook exists |
| I1 auth.rejects_anonymous | I | must | declared auth enforced: anonymous rejected (§7.4, §3.3.2) |
| I2 auth.rejects_wrong | I | must | wrong credentials rejected (§7.4) |
| I3 auth.challenge | I | should | 401 includes challenge information (WWW-Authenticate) (§3.3.2, §7.4) |
| J1 extension.required | J | must | a required extension not requested → ExtensionSupportRequiredError (§3.3.4) |
| K1 errors.mapping | K | must | every A2A error the run provoked uses the binding's code (§5.4) |
| K2 errors.payload | K | must | error responses carry code and message (§3.3.2) |
| L1 resilience.resubscribe | L | must | after a dropped stream, SubscribeToTask returns the current Task first, no duplicates (§3.1.6, §3.5.2) |
| L2 resilience.independent | L | must | the task continues when the client stream drops (§3.5.2 task lifecycle independent of streams) |
| L3 resilience.multi_stream | L | must | two streams for the task receive the same events (§3.5.2) |

## Review Focus

1. **A check that cannot apply** (feature not declared, no credentials, no reachable webhook) yields `not_supported`, never `fail`. *Test:* Task 1 `test_not_applicable_is_not_counted`.
2. **A Workbench-side exception inside a check** yields `error` with the exception text, other checks still run. *Test:* Task 1 `test_check_error_is_isolated`.
3. **Destructive probes never touch tasks the run did not create.** *Test:* Task 3 `test_cancel_probe_only_uses_run_tasks`.
4. **Every check has a broken-zoo variant that makes it fail** (except where the SDK server makes the violation impossible; those are listed). *Test:* each area task's `test_detects_*`.
5. **Evidence**: every non-pass result lists the exchange ids of its probes, and secrets stay masked in reports. *Test:* Task 6 `test_report_evidence_and_secrets`.

---

### Task 1: Engine, model, scoring, reports
Files: `core/health/{__init__,model,registry,context,runner,report}.py`, `core/store/models.py` (`HealthRun`), `core/workbench.py` (`self.health`); tests `tests/core/health/test_engine.py`, `test_report.py` (golden JSON).
Interfaces: `Check(id, area, title, spec_ref, level, fix_hint, applies(ctx)->str|None, run(ctx)->Result)`; `Result(status, expected, actual, exchange_ids, duration_ms)`; `HealthService.run(agent_id, *, areas=None, interfaces="selected"|"all", faults=None) -> AsyncIterator[ProgressEvent]`, `.get(run_id)`, `.list(agent_id=None)`, `.report_json(run_id)`, `.report_html(run_id)`.

### Task 2: Areas A, B, C, E + broken zoo
Files: `core/health/checks/{discovery,transport,messaging}.py`; `fixtures/broken.py` (handler subclass with named breaks), `fixtures/zoo.py`/`runner.py` (`breaks=`), `fixtures` CLI `--breaks`. Tests: compliant zoo passes all applicable; each `test_detects_<check>` against a zoo variant.

### Task 3: Areas F, G
Files: `core/health/checks/{tasks,streaming}.py`; breaks for not-found, cancel, list filter/token/artifacts/order, history, stream first event, stream not closing, subscribe first event, subscribe terminal. Tests as above plus `test_cancel_probe_only_uses_run_tasks`.

### Task 4: Areas H, I, J, K
Files: `core/health/checks/{push,security,extensions,errors}.py`; breaks for push capability, push delete, auth leak (declares bearer, enforces nothing), required extension ignored, wrong error codes. Tests as above.

### Task 5: Area L and passive checks
Files: `core/health/checks/resilience.py` (uses the faults layer), `core/health/passive.py` (evaluate recorded exchanges: error code mapping, stream first event, ListTasks artifacts omission) surfaced on exchange records and in Inspect › Checks. Tests: compliant passes; breaks detected; passive findings attached to exchanges.

### Task 6: Surfaces
API: `POST /api/agents/{id}/health/runs` (202, body `{areas?, interfaces?, faults?}`), `GET /api/health/runs?agent_id=`, `GET /api/health/runs/{id}`, `GET /api/health/runs/{id}/report.json|report.html`, WS `health-run:<id>`; `GET /api/exchanges/{id}` adds `checks`. CLI: `a2a-workbench check <url|agent> [--area A,F] [--interface selected|all] [--faults preset|file] [--fail-on fail|warn] [--format json|html|text] [--out file]` (exit 1 when results at/over `--fail-on`). MCP: `run_health_check(agent, areas?, interfaces?)`, `list_findings(run_id?, agent?, status?)`. Web: Health tab (run with warning and area picker, score, findings by area with expected/actual/fix/spec ref and evidence links into Inspect, history of runs, download JSON/HTML), sidebar "Health checks" page (latest run per agent), Inspect › Checks. `skills/a2a-health-check/SKILL.md` (Claude Code skill) + `docs/agents.md`. Tests per surface, `test_report_evidence_and_secrets`.

### Task 7: E2E and docs
E2E: run a health check on the zoo from the Health tab, see the score and a finding with its evidence. Docs: README Health section, agents.md, spec §3 row H header name fix.
