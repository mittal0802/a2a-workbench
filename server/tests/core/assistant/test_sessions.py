import asyncio

import pytest

from a2a_workbench.core.a2a_json import card_from_json
from a2a_workbench.core.assistant.service import AssistantService, Limits, SessionIn
from a2a_workbench.fixtures.idp import IDP_CLIENT, IdpServer
from a2a_workbench.fixtures.llm import ScriptedAdapter
from a2a_workbench.fixtures.runner import ZooServer


@pytest.fixture
def adapter():
    return ScriptedAdapter()


@pytest.fixture
async def svc(wb, adapter):
    await wb.provider_keys.put("openai", "test-key-123456")
    service = AssistantService(wb, adapter_factory=lambda *a, **k: adapter, watch_interval_s=0.2)
    yield service
    await service.close()


@pytest.fixture
async def agent(wb, zoo):
    return await wb.agents.add(zoo.base_url)


async def _session(svc, agent, **kw):
    return await svc.create(
        SessionIn(provider="openai", model="scripted", agent_ids=[agent.id], **kw)
    )


async def _turn(svc, sid, text):
    return [s async for s in svc.send(sid, text)]


def _kinds(steps):
    return [s.kind for s in steps]


async def test_rewrite_mode_answers_question_itself(svc, agent):
    s = await _session(svc, agent)
    steps = await _turn(svc, s.id, "ask")
    results = [st for st in steps if st.kind == "tool_result"]
    assert [r.data["state"] for r in results] == ["input_required", "completed"]
    assert results[1].data["answered_by"] == "assistant"
    assert steps[-1].kind == "done" and steps[-1].data["text"] == "Done: You chose: B"
    assert (await svc.get(s.id)).status == "idle"
    assert results[0].data["conversation_id"] == results[1].data["conversation_id"]


async def test_rewrite_mode_can_ask_the_user(svc, agent):
    s = await _session(svc, agent)
    first = await _turn(svc, s.id, "ask me")
    assert first[-1].data["text"] == "Question from the agent: Which option should I pick: A or B?"
    task_id = next(st for st in first if st.kind == "tool_result").data["task_id"]
    second = await _turn(svc, s.id, "A")
    call = next(st for st in second if st.kind == "tool_call")
    assert call.data["arguments"]["task_id"] == task_id


async def test_pass_through_question_goes_to_user_and_reply_to_agent(svc, agent, adapter):
    s = await _session(svc, agent, response_mode="pass_through")
    first = await _turn(svc, s.id, "ask")
    paused = first[-1]
    assert paused.kind == "paused" and paused.data["reason"] == "input_required"
    assert paused.data["question"] == "Which option should I pick: A or B?"
    assert (await svc.get(s.id)).status == "awaiting_user"
    calls_before = adapter.calls
    second = await _turn(svc, s.id, "A")
    direct = next(st for st in second if st.kind == "tool_result")
    assert direct.data["answered_by"] == "user" and direct.data["state"] == "completed"
    assert adapter.calls == calls_before + 1
    assert second[-1].kind == "done" and second[-1].data["text"] == "Done: You chose: A"
    outputs = [st for st in second if st.kind == "agent_output"]
    assert any(p.get("text") == "You chose: A" for o in outputs for p in o.data["parts"])


async def test_pass_through_streams_agent_output_steps(svc, agent):
    s = await _session(svc, agent, response_mode="pass_through")
    steps = await _turn(svc, s.id, "stream")
    outputs = [st for st in steps if st.kind == "agent_output"]
    assert "".join(p.get("text", "") for o in outputs for p in o.data["parts"]).endswith(
        "Streaming in four pieces."
    )
    result = next(st for st in steps if st.kind == "tool_result")
    assert result.data["shown_to_user"] is True


async def test_rejected_call_is_reported_to_the_llm(svc, agent, wb):
    s = await _session(svc, agent)
    async for _ in svc.send(s.id, "echo hi"):
        pass
    steps = [
        st
        async for st in svc._run_calls(
            s.id,
            [{"name": "call_zoo_agent", "arguments": {"message": "x", "context_id": "invented"}}],
        )
    ]
    rejected = next(st for st in steps if st.kind == "rejected_call")
    assert rejected.data["rule"] == "context_not_issued"
    sess = await svc._load(s.id)
    assert sess.transcript[-1]["is_error"] is True and "rejected" in sess.transcript[-1]["text"]


async def test_step_limit_stops_the_run(svc, agent):
    s = await _session(svc, agent, limits=Limits(max_steps=3))
    steps = await _turn(svc, s.id, "loop forever")
    assert steps[-1].kind == "limit" and steps[-1].data["limit"] == "max_steps"
    assert _kinds(steps).count("assistant") == 3


async def test_token_budget_stops_the_run(svc, agent):
    s = await _session(svc, agent, limits=Limits(token_budget=10))
    steps = await _turn(svc, s.id, "loop forever")
    assert steps[-1].kind == "limit" and steps[-1].data["limit"] == "token_budget"


async def test_missing_provider_key_is_an_error_step(wb, agent):
    svc = AssistantService(wb, adapter_factory=lambda *a, **k: ScriptedAdapter())
    s = await svc.create(SessionIn(provider="gemini", model="x", agent_ids=[agent.id]))
    steps = await _turn(svc, s.id, "echo")
    assert steps[-1].kind == "error" and steps[-1].data["category"] == "auth"
    assert "gemini" in steps[-1].data["message"].lower()
    await svc.close()


async def test_steps_are_persisted_and_published(svc, agent, wb):
    s = await _session(svc, agent)
    async with wb.bus.subscription(f"assistant:{s.id}") as queue:
        steps = await _turn(svc, s.id, "echo hi")
        published = []
        while not queue.empty():
            published.append(queue.get_nowait())
    stored = await svc.steps(s.id)
    assert [st.seq for st in stored] == list(range(1, len(steps) + 1))
    assert [p["step"]["seq"] for p in published if p["type"] == "step"] == [st.seq for st in stored]


async def test_stop_cancels_a_running_turn(svc, agent):
    s = await _session(svc, agent, limits=Limits(call_timeout_s=30))
    gen = svc.send(s.id, "stall 10")
    first = await gen.__anext__()
    assert first.kind == "user"
    task = asyncio.ensure_future(_drain(gen))
    await asyncio.sleep(0.5)
    await svc.stop(s.id)
    steps = await asyncio.wait_for(task, 5)
    assert steps[-1].kind == "limit" and steps[-1].data["limit"] == "stopped"
    assert (await svc.get(s.id)).status == "stopped"


async def _drain(gen):
    return [s async for s in gen]


@pytest.fixture(scope="module")
def idp():
    with IdpServer() as server:
        yield server


@pytest.fixture(scope="module")
def oauth_zoo(idp):
    with ZooServer(auth="oauth", idp=idp.idp, grpc=False) as zoo:
        yield zoo


async def _sign_in(wb, agent, scopes):
    await wb.auth.sign_in(
        agent.id,
        "oauth",
        flow="client_credentials",
        client_id=IDP_CLIENT["id"],
        client_secret=IDP_CLIENT["secret"],
        scopes=scopes,
        card=card_from_json(agent.card),
    )


async def test_auth_required_pauses_and_resumes_after_sign_in(svc, wb, oauth_zoo):
    agent = await wb.agents.add(oauth_zoo.base_url)
    await _sign_in(wb, agent, ["a2a:invoke"])
    s = await _session(svc, agent)
    first = await _turn(svc, s.id, "hold AI175")
    paused = first[-1]
    assert paused.kind == "paused" and paused.data["reason"] == "auth_required"
    assert paused.data["agent_id"] == agent.id and "booking.write" in paused.data["question"]
    assert (await svc.get(s.id)).status == "awaiting_sign_in"
    await _sign_in(wb, agent, ["a2a:invoke", "booking.write"])
    resumed = [st async for st in svc.resume(s.id)]
    assert resumed[0].kind == "resumed"
    assert resumed[-1].kind == "done" and resumed[-1].data["text"] == "Done: Held AI175."


async def test_task_helpers_only_take_ids_the_agent_returned(svc, agent, wb):
    s = await _session(svc, agent)
    steps = [
        st
        async for st in svc._run_calls(
            s.id,
            [
                {
                    "name": "get_task",
                    "arguments": {"agent": "call_zoo_agent", "task_id": "invented-123"},
                },
                {
                    "name": "cancel_task",
                    "arguments": {"agent": "call_zoo_agent", "task_id": "invented-456"},
                },
            ],
        )
    ]
    rejected = [st for st in steps if st.kind == "rejected_call"]
    assert [r.data["rule"] for r in rejected] == ["task_unknown", "task_unknown"]
    assert not any(st.kind == "tool_result" for st in steps)
    follow = [
        st
        async for st in svc._run_calls(
            s.id,
            [{"name": "call_zoo_agent", "arguments": {"message": "x", "task_id": "invented-123"}}],
        )
    ]
    assert any(st.kind == "rejected_call" and st.data["rule"] == "task_unknown" for st in follow)
    assert (await wb.exchanges.list(agent_id=agent.id)) == [] or all(
        e["operation"] not in ("get_task", "cancel_task", "send_message")
        for e in await wb.exchanges.list(agent_id=agent.id)
    )


async def test_error_results_do_not_make_ids_known(svc, agent, wb):
    from a2a_workbench.core.assistant.executor import ToolResult
    from a2a_workbench.core.assistant.tools import SessionIds

    s = await _session(svc, agent)
    await svc._record(
        s.id,
        agent.id,
        ToolResult(
            agent="Zoo",
            kind="error",
            task_id="t-err",
            context_id="c-err",
            error={"category": "protocol"},
        ),
    )
    ids = SessionIds((await svc._load(s.id)).ids)
    assert not ids.task_known(agent.id, "t-err") and not ids.context_known(agent.id, "c-err")


def _assert_every_call_answered(transcript):
    open_ids = []
    for m in transcript:
        if m["role"] == "assistant":
            assert not open_ids, f"unanswered tool calls {open_ids}"
            open_ids = [c["id"] for c in m["tool_calls"]]
        elif m["role"] == "tool":
            open_ids.remove(m["tool_call_id"])
        else:
            assert not open_ids, f"unanswered tool calls {open_ids}"
    assert not open_ids


async def test_stop_during_a_call_leaves_a_valid_transcript(svc, agent):
    s = await _session(svc, agent)
    gen = svc.send(s.id, "slow 3")
    task = asyncio.ensure_future(_drain(gen))
    await asyncio.sleep(0.6)
    await svc.stop(s.id)
    await asyncio.wait_for(task, 5)
    _assert_every_call_answered((await svc._load(s.id)).transcript)
    steps = await _turn(svc, s.id, "echo again")
    assert steps[-1].kind == "done"
    _assert_every_call_answered((await svc._load(s.id)).transcript)


async def test_failure_during_a_call_leaves_a_valid_transcript(svc, agent, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("agent call exploded")

    monkeypatch.setattr(svc._executor, "call", boom)
    s = await _session(svc, agent)
    steps = await _turn(svc, s.id, "echo hi")
    assert steps[-1].kind == "error" and "exploded" in steps[-1].data["message"]
    _assert_every_call_answered((await svc._load(s.id)).transcript)


async def test_a_second_turn_while_one_runs_is_refused_and_stop_hits_the_running_one(svc, agent):
    from a2a_workbench.core.assistant.service import TurnInProgressError

    s = await _session(svc, agent)
    first = asyncio.ensure_future(_drain(svc.send(s.id, "slow 3")))
    await asyncio.sleep(0.3)
    with pytest.raises(TurnInProgressError):
        svc.send(s.id, "echo second")
    with pytest.raises(TurnInProgressError):
        svc.resume(s.id)
    await svc.stop(s.id)
    steps = await asyncio.wait_for(first, 5)
    assert steps[-1].kind == "limit" and steps[-1].data["limit"] == "stopped"
    after = await _turn(svc, s.id, "echo third")
    assert after[-1].kind == "done"
