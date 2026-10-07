# Phase 2 — Every Binding and Version, Tasks, Failure Injection, MCP: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Talk to any agent over JSON-RPC, HTTP+JSON **and gRPC**, on protocol **v1.0 or v0.3**; manage tasks (get, list with every filter and pagination, cancel, resubscribe); inject network failures beneath the SDK and recover with resubscribe and gap analysis; fetch and diff the extended agent card; and expose all of it through the CLI and a new **MCP server** for AI agents.

**Architecture:** gRPC uses the SDK's `GrpcTransport` through `ClientConfig.grpc_channel_factory`; our factory builds a `grpc.aio` channel with two client interceptors, one recording exchanges and one injecting faults. HTTP traffic gets a `FaultTransport` between the `RecordingTransport` and the network. Fault profiles are per-request data (`SendOptions.faults` and an equivalent argument on task operations), so runs are explicit and reproducible. A new `TaskService` wraps the SDK task methods. `ConversationService` gains `resubscribe` and `check_status`, which emit a `recovered` timeline event carrying a gap analysis. The MCP server (`mcp` 2.x `MCPServer`) is a thin layer over core, like the API and CLI.

**Tech Stack:** additions are `a2a-sdk[grpc]` (grpcio) and `mcp>=2.3,<3`.

**Spec:** `docs/superpowers/specs/2026-10-07-a2a-workbench-design.md` (§3 rows B, F, G, J, L; §5.1, §5.7, §5.9; §12 Phase 2)

## Global Constraints

- All of Phase 1's Global Constraints still apply (official SDK only; no invented protocol fields; docstrings describe only the function; core has no web/CLI/MCP imports).
- Fault injection only disturbs connections and bytes beneath the SDK; it never builds or alters A2A messages. Every injected fault is labelled in the recorded exchange (`Exchange.fault`).
- Fault kinds: `refuse`, `dns_fail`, `tls_fail`, `connect_timeout`, `read_timeout`, `delay`, `reset`, `drop_stream`, `truncate`, `garble`, `http_status`, `expire_token`. Modes: `once`, `always`, `probability` (seeded).
- New timeline kinds: `connection_lost` (a transport failure after a task was created and before it reached a terminal or interrupted state) and `recovered` (result of resubscribe or check status, with gap analysis).
- gRPC interface URLs are accepted as `host:port`, `grpc://host:port`, `http://host:port` (insecure) or `grpcs://host:port`, `https://host:port` (TLS).

## Review Focus

1. **A stream drops after N events, then the user resubscribes:** the timeline shows exactly the missed events once, and the gap analysis says whether the first resubscribed event was the Task snapshot. *Test:* Task 6 `test_resubscribe_after_dropped_stream_recovers_without_duplicates`.
2. **gRPC agent unreachable:** an `error` (transport) event, not a hang or crash. *Test:* Task 2 `test_grpc_unreachable_is_transport_error`.
3. **v0.3 agent:** the same chat works and Inspect shows legacy method names (`message/send`). *Test:* Task 3 `test_legacy_v03_agent_round_trip`.
4. **ListTasks pagination:** following `next_page_token` returns every task exactly once. *Test:* Task 5 `test_list_tasks_pagination_covers_all`.
5. **Probability faults are reproducible:** the same seed gives the same sequence. *Test:* Task 1 `test_probability_mode_is_seeded`.

---

## File Structure

```
server/a2a_workbench/core/
  faults/__init__.py
  faults/profile.py          # FaultRule, FaultProfile, presets, validation
  faults/injector.py         # FaultInjector: rule matching + counters + seeded RNG
  faults/http.py             # FaultTransport (httpx)
  faults/grpc.py             # FaultGrpcInterceptor (grpc.aio)
  connection/grpc.py         # RecordingGrpcInterceptor, build_grpc_channel_factory
  connection/http.py         # + faults parameter
  connection/client.py       # + GRPC binding, faults parameter
  connection/recorder.py     # + Exchange.fault
  tasks/__init__.py
  tasks/service.py           # TaskService: get/list/cancel/subscribe
  registry/service.py        # + extended card fetch, card diff
  registry/diff.py           # card_diff
  conversations/service.py   # + resubscribe, check_status, connection_lost, gap analysis
  conversations/gaps.py      # analyze_recovery
server/a2a_workbench/fixtures/zoo.py      # + gRPC server, v0.3 variant, extended card, extension, long/stall behaviours
server/a2a_workbench/fixtures/runner.py   # + grpc port, legacy flag, restart()
server/a2a_workbench/api/routes_tasks.py  # tasks endpoints
server/a2a_workbench/api/routes_agents.py # + extended card
server/a2a_workbench/api/routes_conversations.py # + resubscribe, check-status
server/a2a_workbench/api/routes_misc.py   # + fault presets
server/a2a_workbench/cli/main.py          # + tasks, faults, card --extended, --faults, mcp
server/a2a_workbench/mcp/__init__.py
server/a2a_workbench/mcp/server.py        # build_mcp_server(workbench) -> MCPServer
web/src/features/tasks/{TasksView,TaskDetail}.tsx
web/src/features/chat/{NetworkConditions,RecoveryCard}.tsx
web/src/features/about/CardDiff.tsx
docs/agents.md
```

---

### Task 1: Fault profiles and injector

**Files:** create `core/faults/{__init__,profile,injector}.py`; test `tests/core/faults/test_profile.py`, `test_injector.py`.

**Interfaces — Produces:**
- `FaultKind` literal (the 12 kinds); `FaultMatch(operation: str | None = None, binding: str | None = None, nth_call: int | None = None)`; `FaultRule(match: FaultMatch = FaultMatch(), kind: FaultKind, mode: Literal["once","always","probability"] = "once", probability: float = 1.0, params: dict[str, Any] = {})`; `FaultProfile(name: str = "custom", rules: list[FaultRule] = [], seed: int = 0)`.
- `PRESETS: dict[str, FaultProfile]` with keys `stable`, `flaky_stream`, `slow_agent`, `offline`, `rate_limited`, `server_error`.
- `load_profile(spec: str) -> FaultProfile`: a preset name or a path to a JSON file; raises `ValueError` with a readable message.
- `FaultInjector(profile)`: `.decide(operation: str, binding: str) -> FaultRule | None` (increments the per-operation call counter; applies `once`, `always`, and seeded `probability`).

- [ ] **Step 1: failing tests**

```python
# tests/core/faults/test_injector.py
from a2a_workbench.core.faults.injector import FaultInjector
from a2a_workbench.core.faults.profile import FaultMatch, FaultProfile, FaultRule


def _inj(*rules, seed=0):
    return FaultInjector(FaultProfile(rules=list(rules), seed=seed))


def test_once_fires_only_first_match():
    inj = _inj(FaultRule(kind="refuse"))
    assert inj.decide("send_message", "JSONRPC").kind == "refuse"
    assert inj.decide("send_message", "JSONRPC") is None


def test_always_fires_every_time():
    inj = _inj(FaultRule(kind="delay", mode="always", params={"ms": 1}))
    assert all(inj.decide("x", "JSONRPC") for _ in range(3))


def test_match_operation_binding_and_nth_call():
    inj = _inj(FaultRule(kind="reset", mode="always",
                         match=FaultMatch(operation="send_message", binding="GRPC", nth_call=2)))
    assert inj.decide("send_message", "GRPC") is None
    assert inj.decide("get_task", "GRPC") is None
    assert inj.decide("send_message", "GRPC").kind == "reset"
    assert inj.decide("send_message", "JSONRPC") is None


def test_probability_mode_is_seeded():
    rule = FaultRule(kind="refuse", mode="probability", probability=0.5)
    a = [bool(_inj(rule, seed=7).decide("x", "JSONRPC")) for _ in range(1)]
    seq = lambda: [bool(i.decide("x", "JSONRPC")) for i in [_inj(rule, seed=7)] for _ in range(20)]
    assert seq() == seq()
    assert any(seq()) and not all(seq())
```

```python
# tests/core/faults/test_profile.py
import json

import pytest

from a2a_workbench.core.faults.profile import PRESETS, FaultProfile, load_profile


def test_presets_exist_and_validate():
    assert set(PRESETS) >= {"stable", "flaky_stream", "slow_agent", "offline", "rate_limited", "server_error"}
    assert PRESETS["stable"].rules == []
    assert PRESETS["flaky_stream"].rules[0].kind == "drop_stream"


def test_load_preset_by_name():
    assert load_profile("offline").rules[0].kind == "refuse"


def test_load_from_file(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"name": "mine", "rules": [{"kind": "delay", "params": {"ms": 5}}]}))
    assert load_profile(str(p)).name == "mine"


def test_bad_spec_is_value_error(tmp_path):
    with pytest.raises(ValueError):
        load_profile("no-such-preset")
    bad = tmp_path / "b.json"
    bad.write_text('{"rules": [{"kind": "explode"}]}')
    with pytest.raises(ValueError):
        load_profile(str(bad))


def test_param_validation():
    with pytest.raises(ValueError):
        FaultProfile.model_validate({"rules": [{"kind": "drop_stream", "params": {}}]})
    with pytest.raises(ValueError):
        FaultProfile.model_validate({"rules": [{"kind": "http_status", "params": {"code": 99}}]})
```

- [ ] **Step 2:** run, expect import failure. **Step 3:** implement. Required params per kind: `delay` → `ms` (int ≥ 0); `drop_stream` → `after_events` (int ≥ 0) or `after_ms` (int ≥ 0); `truncate` → `bytes` (int ≥ 0); `http_status` → `code` (100–599), optional `retry_after` (int); `read_timeout` → optional `after_ms`. Presets: `stable` (no rules); `flaky_stream` (drop_stream once after 3 events on `send_message`); `slow_agent` (delay 1500 ms always); `offline` (refuse always); `rate_limited` (http_status 429 with retry_after 2, once); `server_error` (http_status 503 always). `FaultInjector` keeps `counts[operation]` and a `random.Random(profile.seed)`; for each call it increments the count and returns the first rule whose match fits (nth_call compares to the count), honouring `once` (tracks fired rule indexes) and `probability` (`rng.random() < probability`).
- [ ] **Step 4:** run → PASS. **Step 5:** commit `feat(core): fault profiles, presets and seeded injector`.

---

### Task 2: Fault transport (HTTP), gRPC channel with recording and faults, gRPC binding

**Files:** create `core/faults/http.py`, `core/faults/grpc.py`, `core/connection/grpc.py`; modify `connection/recorder.py` (`Exchange.fault`), `connection/http.py`, `connection/client.py` (`SUPPORTED_BINDINGS += "GRPC"`, `open_client(..., faults: FaultProfile | None = None)`); add `a2a-sdk[grpc,http-server,signing]` to deps. Fixture: zoo serves gRPC (Task 3 depends on this; implement the zoo gRPC server here). Tests: `tests/core/faults/test_http_faults.py`, `tests/core/test_grpc.py`.

**Interfaces — Produces:**
- `FaultTransport(inner, injector, binding="HTTP")`: sets `request.extensions["a2aw_fault"]` to the kind it applied.
- `RecordingTransport` copies `request.extensions.get("a2aw_fault")` into `Exchange.fault`.
- `build_http_client(sink, *, faults: FaultProfile | None = None, ...)`.
- `parse_grpc_target(url) -> tuple[str, bool]` → `(host:port, secure)`.
- `build_grpc_channel_factory(sink, *, faults=None) -> Callable[[str], grpc.aio.Channel]`.
- `RecordingGrpcInterceptor(sink)`: records unary and server-streaming calls as `Exchange(http_method="GRPC", url="grpc://<target>/<Service>/<Method>", status=<grpc code int>, request_body=<JSON>, response_body=<JSON> | frames=[<JSON per message>])`.
- `FaultGrpcInterceptor(injector)`: maps kinds to `grpc.aio.AioRpcError` codes (`refuse`/`dns_fail`/`tls_fail`/`reset`/`drop_stream` → UNAVAILABLE; timeouts → DEADLINE_EXCEEDED; `http_status` 401→UNAUTHENTICATED, 403→PERMISSION_DENIED, 404→NOT_FOUND, 429→RESOURCE_EXHAUSTED, 5xx→UNAVAILABLE/INTERNAL; `expire_token`→UNAUTHENTICATED); `truncate`/`garble` are not applicable to gRPC and are recorded as `fault="<kind>(not applicable)"` without effect.

- [ ] **Step 1: failing tests** (MockTransport-based for HTTP faults):

```python
# tests/core/faults/test_http_faults.py
import httpx
import pytest

from a2a_workbench.core.connection.recorder import RecordingTransport, recording_scope
from a2a_workbench.core.faults.http import FaultTransport
from a2a_workbench.core.faults.injector import FaultInjector
from a2a_workbench.core.faults.profile import FaultProfile, FaultRule

SSE = b"".join(f'data: {{"n":{i}}}\n\n'.encode() for i in range(5))


def _client(rule, handler=None, sink=None):
    inner = httpx.MockTransport(handler or (lambda r: httpx.Response(200, content=SSE, headers={"content-type": "text/event-stream"})))
    ft = FaultTransport(inner, FaultInjector(FaultProfile(rules=[rule])), binding="JSONRPC")
    transport = RecordingTransport(sink, ft) if sink else ft
    return httpx.AsyncClient(transport=transport)


class Sink(list):
    async def __call__(self, ex):
        self.append(ex)


@pytest.mark.parametrize("kind,exc", [("refuse", httpx.ConnectError), ("dns_fail", httpx.ConnectError),
                                      ("tls_fail", httpx.ConnectError), ("connect_timeout", httpx.ConnectTimeout),
                                      ("read_timeout", httpx.ReadTimeout)])
async def test_connection_faults_raise(kind, exc):
    async with _client(FaultRule(kind=kind)) as c:
        with pytest.raises(exc):
            await c.get("http://x/")


async def test_drop_stream_after_events():
    async with _client(FaultRule(kind="drop_stream", params={"after_events": 2})) as c:
        got = b""
        with pytest.raises(httpx.ReadError):
            async with c.stream("POST", "http://x/") as r:
                async for chunk in r.aiter_bytes():
                    got += chunk
    assert got.count(b"\n\n") == 2


async def test_http_status_short_circuits():
    async with _client(FaultRule(kind="http_status", params={"code": 429, "retry_after": 3})) as c:
        r = await c.get("http://x/")
    assert r.status_code == 429 and r.headers["retry-after"] == "3"


async def test_truncate_and_garble_change_bytes():
    async with _client(FaultRule(kind="truncate", params={"bytes": 4})) as c:
        assert len((await c.get("http://x/")).content) == 4
    async with _client(FaultRule(kind="garble")) as c:
        assert (await c.get("http://x/")).content != SSE


async def test_delay_then_forward():
    async with _client(FaultRule(kind="delay", params={"ms": 10})) as c:
        assert (await c.get("http://x/")).status_code == 200


async def test_injected_fault_is_labelled_in_recording():
    sink = Sink()
    async with _client(FaultRule(kind="refuse"), sink=sink) as c:
        with recording_scope("send_message"), pytest.raises(httpx.ConnectError):
            await c.get("http://x/")
    assert sink[0].fault == "refuse"


async def test_expire_token_returns_401_with_challenge():
    async with _client(FaultRule(kind="expire_token")) as c:
        r = await c.get("http://x/")
    assert r.status_code == 401 and "invalid_token" in r.headers["www-authenticate"]
```

```python
# tests/core/test_grpc.py
import pytest
from a2a.types import Message, Part, Role, SendMessageRequest

from a2a_workbench.core.connection.cards import fetch_card
from a2a_workbench.core.connection.client import open_client
from a2a_workbench.core.connection.grpc import parse_grpc_target
from a2a_workbench.core.faults.profile import FaultProfile, FaultRule


class Sink(list):
    async def __call__(self, ex):
        self.append(ex)


def test_parse_grpc_target():
    assert parse_grpc_target("localhost:50051") == ("localhost:50051", False)
    assert parse_grpc_target("grpc://h:1") == ("h:1", False)
    assert parse_grpc_target("http://h:1/a2a") == ("h:1", False)
    assert parse_grpc_target("grpcs://h:443") == ("h:443", True)
    assert parse_grpc_target("https://h") == ("h:443", True)


def _req(text):
    return SendMessageRequest(message=Message(message_id="m", role=Role.ROLE_USER, parts=[Part(text=text)]))


async def test_grpc_streaming_round_trip_is_recorded(zoo):
    sink = Sink()
    card = (await fetch_card(zoo.base_url, sink)).card
    iface = next(i for i in card.supported_interfaces if i.protocol_binding == "GRPC")
    async with await open_client(card, iface, sink, streaming=True) as client:
        events = [e async for e in client.send_message(_req("stream"))]
    assert events[-1].status_update.status.state == 3
    grpc_ex = [e for e in sink if e.http_method == "GRPC"]
    assert grpc_ex[-1].url.endswith("/SendStreamingMessage") and len(grpc_ex[-1].frames) == len(events)


async def test_grpc_unreachable_is_transport_error():
    from a2a.types import AgentCard, AgentInterface
    from a2a_workbench.core.conversations.errors import classify_error
    card = AgentCard(name="x", supported_interfaces=[AgentInterface(url="127.0.0.1:1", protocol_binding="GRPC", protocol_version="1.0")])
    async with await open_client(card, card.supported_interfaces[0], Sink(), streaming=False) as client:
        with pytest.raises(Exception) as info:
            [e async for e in client.send_message(_req("echo"))]
    assert classify_error(info.value)["category"] == "transport"


async def test_grpc_drop_stream_fault(zoo):
    sink = Sink()
    card = (await fetch_card(zoo.base_url, sink)).card
    iface = next(i for i in card.supported_interfaces if i.protocol_binding == "GRPC")
    faults = FaultProfile(rules=[FaultRule(kind="drop_stream", params={"after_events": 2})])
    async with await open_client(card, iface, sink, streaming=True, faults=faults) as client:
        got = []
        with pytest.raises(Exception):
            async for e in client.send_message(_req("stream")):
                got.append(e)
    assert len(got) == 2
    assert [e for e in sink if e.http_method == "GRPC"][-1].fault == "drop_stream"
```

`classify_error` gains: `grpc.aio.AioRpcError` with UNAVAILABLE / DEADLINE_EXCEEDED → `transport`; UNAUTHENTICATED / PERMISSION_DENIED → `auth`; others → `protocol` with `grpc_status`. Add `tests/core/conversations/test_errors.py::test_grpc_codes`.

- [ ] **Step 2–4:** implement and pass. The zoo gains a gRPC server: `build_zoo_app(base_url, *, grpc_port=None, ...)` registers a Starlette lifespan that starts `grpc.aio.server()` with `GrpcHandler(handler)` via `a2a_pb2_grpc.add_A2AServiceServicer_to_server`, and the card lists `AgentInterface(url=f"127.0.0.1:{grpc_port}", protocol_binding="GRPC", protocol_version="1.0")`. `ZooServer` picks a second free port and runs uvicorn with `lifespan="on"`.
- [ ] **Step 5:** commit `feat(core): grpc binding with recording, and http/grpc fault injection beneath the SDK`.

---

### Task 3: v0.3 legacy agent and protocol-version coverage

**Files:** modify `fixtures/zoo.py` (`legacy: bool` builds a card whose interfaces have `protocol_version="0.3"` and routes created with `enable_v0_3_compat=True`), `fixtures/runner.py` (`ZooServer(legacy=True)`), `tests/conftest.py` (`legacy_zoo` fixture). Tests: `tests/core/test_legacy.py`.

- [ ] **Step 1: failing tests**

```python
async def test_legacy_v03_agent_round_trip(wb, legacy_zoo):
    agent = await wb.agents.add(legacy_zoo.base_url)
    assert {i.protocol_version for i in agent.interfaces} == {"0.3"}
    conv = await wb.conversations.create(agent.id)
    events = [e async for e in wb.conversations.send(conv.id, [TextPartInput(text="stream")], SendOptions())]
    assert events[-1].data["state"] == "completed"
    ex = await wb.exchanges.get(events[-1].exchange_id)
    assert '"message/stream"' in ex["request_body"]


async def test_legacy_rest_binding(wb, legacy_zoo):
    agent = await wb.agents.add(legacy_zoo.base_url)
    rest = next(i for i in agent.interfaces if i.binding == "HTTP+JSON")
    await wb.agents.set_interface(agent.id, rest.url)
    conv = await wb.conversations.create(agent.id)
    events = [e async for e in wb.conversations.send(conv.id, [TextPartInput(text="echo v03")], SendOptions(stream=False))]
    assert events[-1].data["state"] == "completed"
```

- [ ] **Steps 2–5:** implement, pass, commit `test: legacy v0.3 zoo agent and compat coverage`.

---

### Task 4: Extended agent card and card diff

**Files:** create `core/registry/diff.py`; modify `registry/service.py` (`get_extended_card(agent_id) -> ExtendedCardOut`), `store/models.py` (`Agent.extended_card: dict | None`), zoo (`capabilities.extended_agent_card=True`, extended card with an extra skill `visa`), API (`POST /api/agents/{id}/extended-card`), CLI (`card --extended`), web About (Public / Extended / Differences toggle). Tests: `tests/core/test_card_diff.py`, `tests/core/test_extended_card.py`, `web/src/features/about/CardDiff.test.tsx`.

**Interfaces:** `card_diff(public: dict, extended: dict) -> list[dict]` with entries `{"path": "skills[visa]", "change": "added"|"removed"|"changed", "public": Any, "extended": Any}`; lists of objects with `id` (skills) or `uri` (extensions) are matched by that key, other lists by index. `ExtendedCardOut(card: dict, diff: list[dict], exchange_ids: list[str])`. Errors: `ExtendedAgentCardNotConfiguredError` and `UnsupportedOperationError` reach the caller as `protocol` errors (422 in the API).

- [ ] **Step 1: failing tests**

```python
def test_diff_matches_skills_by_id():
    a = {"name": "x", "skills": [{"id": "s1", "name": "A"}]}
    b = {"name": "x", "skills": [{"id": "s1", "name": "A2"}, {"id": "s2", "name": "B"}]}
    assert card_diff(a, b) == [
        {"path": "skills[s1].name", "change": "changed", "public": "A", "extended": "A2"},
        {"path": "skills[s2]", "change": "added", "public": None, "extended": {"id": "s2", "name": "B"}},
    ]


async def test_extended_card_fetch_and_diff(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    out = await wb.agents.get_extended_card(agent.id)
    assert any(d["path"] == "skills[visa]" and d["change"] == "added" for d in out.diff)
    assert (await wb.agents.row(agent.id)).extended_card["name"] == "Zoo agent"
```

- [ ] **Steps 2–5:** implement, pass, commit `feat: extended agent card with differences view`.

---

### Task 5: Task operations (core, API, CLI, web Tasks tab)

**Files:** create `core/tasks/{__init__,service}.py`, `api/routes_tasks.py`, `web/src/features/tasks/{TasksView,TaskDetail}.tsx`; modify `workbench.py`, `cli/main.py` (`tasks` group), `AgentPage.tsx` (Tasks tab). Tests: `tests/core/test_tasks.py`, `tests/api/test_tasks_api.py`, `tests/cli/test_tasks_cli.py`, `web/src/features/tasks/TasksView.test.tsx`.

**Interfaces:**
- `ListTasksFilter(context_id: str | None, status: str | None (short state name), status_timestamp_after: datetime | None, include_artifacts: bool | None, history_length: int | None, page_size: int | None, page_token: str | None)`.
- `TaskService(db, sink)`: `async get(agent_id, task_id, *, history_length=None, faults=None) -> dict` (Task JSON + `"state"`), `async list(agent_id, f: ListTasksFilter, *, faults=None) -> dict` (`{"tasks": [...], "next_page_token", "page_size", "total_size"}`), `async cancel(agent_id, task_id, *, metadata=None, faults=None) -> dict`, `subscribe(agent_id, task_id, *, faults=None) -> AsyncIterator[dict]` (StreamResponse JSON with `"kind"`). Operations are labelled `get_task`, `list_tasks`, `cancel_task`, `subscribe_task` in recordings. Errors are raised as `TaskOperationError(classified: dict)`.
- API: `GET /api/agents/{id}/tasks?context_id&status&status_timestamp_after&include_artifacts&history_length&page_size&page_token`, `GET /api/agents/{id}/tasks/{task_id}?history_length`, `POST /api/agents/{id}/tasks/{task_id}/cancel {metadata?}`; errors return 422 with the classified payload.
- CLI: `tasks list <agent> [--context-id] [--status] [--updated-after ISO] [--include-artifacts/--no-include-artifacts] [--history-length] [--page-size] [--page-token] [--all] [--json]`, `tasks get <agent> <task-id> [--history-length] [--json]`, `tasks cancel <agent> <task-id> [--metadata JSON] [--json]`, `tasks subscribe <agent> <task-id> [--json]` (NDJSON).
- Web Tasks tab: filter bar (status select with plain labels, context id, updated-after datetime, include-results switch, history length, page size), table (title from first user text in history, plain state pill, artifacts count, updated relative time), "Load more" via `next_page_token`, `total_size` display, row actions Open (TaskDetail: status, history as chat bubbles, artifacts through `PartView`), Watch live (resubscribe into the owning conversation if one exists, else into TaskDetail), Stop (cancel).

- [ ] **Step 1: failing tests (core)**

```python
async def _completed_tasks(wb, agent, n):
    conv = await wb.conversations.create(agent.id)
    for i in range(n):
        [e async for e in wb.conversations.send(conv.id, [TextPartInput(text=f"echo {i}")], SendOptions(stream=False))]
    return conv


async def test_get_task_with_history_length(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await _completed_tasks(wb, agent, 1)
    task_id = (await wb.conversations.get(conv.id)).task_id
    task = await wb.tasks.get(agent.id, task_id, history_length=1)
    assert task["id"] == task_id and task["state"] == "completed" and len(task.get("history", [])) <= 1


async def test_list_tasks_filters_by_status_and_context(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await _completed_tasks(wb, agent, 2)
    ctx = (await wb.conversations.get(conv.id)).context_id
    out = await wb.tasks.list(agent.id, ListTasksFilter(context_id=ctx, status="completed"))
    assert len(out["tasks"]) == 2 and all(t["contextId"] == ctx for t in out["tasks"])


async def test_list_tasks_pagination_covers_all(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await _completed_tasks(wb, agent, 5)
    ctx = (await wb.conversations.get(conv.id)).context_id
    seen, token = [], None
    while True:
        page = await wb.tasks.list(agent.id, ListTasksFilter(context_id=ctx, page_size=2, page_token=token))
        seen += [t["id"] for t in page["tasks"]]
        token = page.get("next_page_token")
        if not token:
            break
    assert len(seen) == 5 and len(set(seen)) == 5


async def test_cancel_unknown_task_is_protocol_error(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    with pytest.raises(TaskOperationError) as info:
        await wb.tasks.cancel(agent.id, "nope")
    assert info.value.classified["category"] == "protocol"
    assert info.value.classified["reason"] == "TASK_NOT_FOUND"


async def test_subscribe_running_task_yields_snapshot_first(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    [e async for e in wb.conversations.send(conv.id, [TextPartInput(text="long")], SendOptions(stream=False, return_immediately=True))]
    task_id = (await wb.conversations.get(conv.id)).task_id
    kinds = [e["kind"] async for e in wb.tasks.subscribe(agent.id, task_id)]
    assert kinds[0] == "task" and kinds[-1] == "status_update"
```

(Zoo gains `long`: ten artifact chunks 150 ms apart, then completed; and `stall <secs>`: one status update, then a silent wait.)

- [ ] **Steps 2–5:** implement core, API, CLI and web with their tests; commit in three commits: `feat(core): task operations`, `feat(api,cli): task endpoints and commands`, `feat(web): tasks tab`.

---

### Task 6: Resubscribe, check status, connection-lost and gap analysis

**Files:** create `core/conversations/gaps.py`; modify `conversations/service.py`, `conversations/options.py` (`faults: FaultProfile | None`), `api/routes_conversations.py` (`POST …/resubscribe`, `POST …/check-status`), web `RecoveryCard.tsx`, `Turn.tsx`, `lib/timeline.ts`, `lib/types.ts`. Tests: `tests/core/conversations/test_gaps.py`, `tests/core/test_recovery.py`, `web/src/features/chat/RecoveryCard.test.tsx`.

**Interfaces:**
- `send` emits `connection_lost` (instead of `error`) when the failure is `transport`, a task id is known, and the last state is neither terminal nor interrupted; data: `{"category","message","task_id","last_state"}`.
- `ConversationService.resubscribe(conversation_id, *, faults=None) -> AsyncIterator[TimelineEvent]`: SubscribeToTask on `conv.task_id`; every StreamResponse becomes a normal event; afterwards emits `recovered` with `analyze_recovery(...)`.
- `ConversationService.check_status(conversation_id, *, faults=None)`: GetTask → `task` event, then `recovered` (`method: "get_task"`).
- `analyze_recovery(before: list[TimelineEvent], after: list[TimelineEvent], method: Literal["subscribe","get_task"]) -> dict` returning `{"method", "first_event": kind, "snapshot_first": bool, "state_before", "state_after", "missed_states": [...], "missed_artifacts": [artifact_id...], "duplicate_events": int, "terminal": bool}`. Duplicates: post-snapshot events identical (kind, state, artifact id and parts) to pre-drop events. Missed artifacts: artifact ids in the snapshot or later events not present before.
- Web: an agent turn ending in `connection_lost` shows `RecoveryCard` ("Connection lost while the agent was working", buttons **Resubscribe** and **Check status**); a `recovered` event renders a summary ("Back in sync: snapshot received first ✓, 2 updates you missed, no duplicates") with each item in plain language.

- [ ] **Step 1: failing tests**

```python
async def test_drop_produces_connection_lost(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    opts = SendOptions(faults=FaultProfile(rules=[FaultRule(kind="drop_stream", params={"after_events": 3})]))
    events = [e async for e in wb.conversations.send(conv.id, [TextPartInput(text="long")], opts)]
    assert events[-1].kind == "connection_lost" and events[-1].data["task_id"]


async def test_resubscribe_after_dropped_stream_recovers_without_duplicates(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    opts = SendOptions(faults=FaultProfile(rules=[FaultRule(kind="drop_stream", params={"after_events": 3})]))
    [e async for e in wb.conversations.send(conv.id, [TextPartInput(text="long")], opts)]
    after = [e async for e in wb.conversations.resubscribe(conv.id)]
    recovered = after[-1]
    assert recovered.kind == "recovered"
    assert recovered.data["snapshot_first"] is True
    assert recovered.data["state_after"] == "completed"
    assert recovered.data["duplicate_events"] == 0
    seqs = [e.seq for e in await wb.conversations.events(conv.id)]
    assert seqs == sorted(set(seqs))


async def test_check_status_after_drop(wb, zoo):
    ...  # same setup; check_status yields a task event and recovered(method="get_task")
```

`test_gaps.py` covers `analyze_recovery` on hand-built event lists: snapshot first vs not, missed states, missed artifacts, duplicate counting.

- [ ] **Steps 2–5:** implement, pass, commit `feat: connection-lost detection, resubscribe and check status with gap analysis`.

---

### Task 7: Network conditions UI and fault presets endpoint

**Files:** `api/routes_misc.py` (`GET /api/fault-presets`), web `features/chat/NetworkConditions.tsx` (section inside `OptionsMenu`: preset radio list Stable / Flaky stream / Slow agent / Offline / Rate limited / Server error / Custom JSON editor validated client-side for shape; active-profile banner above the composer "Network conditions: Flaky stream · next message only"), `lib/types.ts` (`SendOptions.faults`). Inspect labels injected faults with an amber "injected: <kind>" tag. Tests: `tests/api/test_faults_api.py`, `web/src/features/chat/NetworkConditions.test.tsx`, Inspect test for the injected tag.

- [ ] Steps: failing tests (preset list endpoint returns the six presets with rules; selecting "Flaky stream" puts the preset's profile into `onSend` options; the banner appears; Inspect shows "injected: drop_stream"), implement, pass, commit `feat(web): network conditions and injected-fault labels`.

---

### Task 8: CLI faults and MCP server

**Files:** `cli/main.py` (`--faults SPEC` on `send` and every `tasks` command; `faults presets [--json]`; `faults validate FILE`; `card --extended`; `mcp [--transport stdio|streamable-http] [--port]`), create `mcp/{__init__,server}.py`, `docs/agents.md`. Tests: `tests/cli/test_faults_cli.py`, `tests/mcp/test_mcp_server.py`.

**Interfaces:** `build_mcp_server(workbench: Workbench) -> MCPServer` registering tools (all JSON in, JSON out; descriptions written for an AI agent):
- `list_agents()`, `add_agent(url)`, `fetch_card(url_or_agent, extended=False)`
- `send_message(agent, text, data=None, file_urls=None, stream=True, accepted_output_modes=None, history_length=None, extensions=None, metadata=None, continue_conversation_id=None, faults=None)` → `{"conversation_id", "events": [...], "final_state"}`
- `get_task(agent, task_id, history_length=None)`, `list_tasks(agent, …filters)`, `cancel_task(agent, task_id)`, `subscribe_task(agent, task_id, timeout_s=30)`
- `resubscribe(conversation_id)`, `check_status(conversation_id)`
- `list_exchanges(conversation_id)`, `get_exchange(exchange_id)`, `fault_presets()`

`a2a-workbench mcp` opens one `Workbench` for the process lifetime (MCPServer `lifespan`).

- [ ] **Step 1: failing tests**

```python
async def test_mcp_tools_drive_an_agent(zoo):
    from mcp.client.client import Client
    async with Workbench.open(Settings()) as wb:
        server = build_mcp_server(wb)
        async with Client(server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"send_message", "list_tasks", "fetch_card", "get_exchange"} <= names
            r = await c.call_tool("send_message", {"agent": zoo.base_url, "text": "stream"})
            body = json.loads(r.content[0].text)
            assert body["final_state"] == "completed"
            ex = json.loads((await c.call_tool("list_exchanges", {"conversation_id": body["conversation_id"]})).content[0].text)
            assert ex[-1]["operation"] == "send_message"
```

CLI: `send --faults flaky_stream` against `long` exits 3 and the last NDJSON line is `connection_lost`; `faults presets --json` lists six; `faults validate bad.json` exits 2.

- [ ] **Steps 2–5:** implement, pass, commit `feat: MCP server and CLI fault options`.

`docs/agents.md`: how an AI agent should test an A2A server with the CLI or MCP (commands, NDJSON shapes, exit codes, recovery workflow).

---

### Task 9: End-to-end and verification

- [ ] Extend `web/e2e/connect-and-chat.spec.ts` with a second test: select **gRPC** in the connection menu, send `stream`, see "Done"; choose **Flaky stream** in Network conditions, send `long`, see "Connection lost", click **Resubscribe**, see "Back in sync". A third test opens the Tasks tab and sees the completed tasks.
- [ ] Full verification: `uv run pytest -q`, `ruff`, `pnpm test`, `pnpm lint`, `scripts/build.sh --no-wheel`, `pnpm e2e`, wheel smoke (`uvx --from server/dist/*.whl a2a-workbench mcp --help`).
- [ ] Commit `test: e2e for grpc, faults, recovery and tasks`.

## Self-Review

- **Spec coverage (Phase 2):** REST+gRPC bindings and switching (T2, connection menu already switches); v0.3 compat (T3); Tasks tab with every filter and pagination, Subscribe, Cancel (T5); extended card and diff (T4); extensions activation (shipped in Phase 1 Options; zoo now declares one in T4); faults layer with presets, UI, recovery and gap analysis (T1, T2, T6, T7); CLI `tasks`, `--faults`, `faults` (T5, T8); MCP server (T8); zoo all bindings, legacy, flaky behaviours (T2, T3, T5).
- **Placeholders:** `test_check_status_after_drop` is described by its assertions in the same block; the UI tasks list concrete behaviours and test assertions.
- **Type consistency:** `FaultProfile`/`FaultRule` are used identically in core, API (`SendOptions.faults`), CLI (`load_profile`) and MCP; timeline kinds `connection_lost`/`recovered` are added to Python `EventKind` and TS `TimelineEvent.kind`.
