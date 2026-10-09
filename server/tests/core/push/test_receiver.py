import json

from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput


def _status_update(task_id, state="TASK_STATE_COMPLETED", context_id="ctx"):
    return json.dumps(
        {"statusUpdate": {"taskId": task_id, "contextId": context_id, "status": {"state": state}}}
    ).encode()


def _headers(hook, *, token=True, auth=True):
    h = {"content-type": "application/json"}
    if auth:
        h["authorization"] = f"{hook.auth_scheme} {hook.credentials}"
    if token:
        h["x-a2a-notification-token"] = hook.token
    return h


async def _setup(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    events = [
        e
        async for e in wb.conversations.send(
            conv.id,
            [TextPartInput(text="slow 20")],
            SendOptions(stream=False, return_immediately=True),
        )
    ]
    task_id = next(e.task_id for e in events if e.task_id)
    hook = await wb.hooks.create(agent.id, task_id=task_id, conversation_id=conv.id)
    return agent, conv, task_id, hook


async def test_accepted_delivery_becomes_a_push_event(wb, zoo):
    agent, conv, task_id, hook = await _setup(wb, zoo)
    assert hook.url.endswith(f"/hooks/{hook.id}") and hook.token and hook.credentials
    status, delivery = await wb.receiver.receive(hook.id, _headers(hook), _status_update(task_id))
    assert status == 200 and delivery.verdict == "accepted" and delivery.kind == "status_update"
    assert delivery.state == "completed" and delivery.task_id == task_id and not delivery.duplicate
    pushes = [e for e in await wb.conversations.events(conv.id) if e.kind == "push"]
    assert len(pushes) == 1 and pushes[0].data["state"] == "completed"
    assert pushes[0].data["payload"]["statusUpdate"]["taskId"] == task_id
    listed = await wb.receiver.deliveries(agent.id)
    assert [d.id for d in listed] == [delivery.id]


async def test_unauthenticated_delivery_is_rejected(wb, zoo):
    agent, conv, task_id, hook = await _setup(wb, zoo)
    status, d = await wb.receiver.receive(
        hook.id, _headers(hook, auth=False), _status_update(task_id)
    )
    assert status == 401 and d.verdict == "rejected" and "unauthenticated" in d.reasons
    wrong = {**_headers(hook), "authorization": "Bearer not-it"}
    status, d = await wb.receiver.receive(hook.id, wrong, _status_update(task_id))
    assert status == 401 and "unauthenticated" in d.reasons
    other = await wb.hooks.create(agent.id, task_id=task_id)
    status, d = await wb.receiver.receive(
        hook.id,
        {**_headers(hook), "x-a2a-notification-token": other.token},
        _status_update(task_id),
    )
    assert status == 401 and "wrong_token" in d.reasons
    status, d = await wb.receiver.receive("no-such-hook", _headers(hook), _status_update(task_id))
    assert status == 404 and d is None
    assert not [e for e in await wb.conversations.events(conv.id) if e.kind == "push"]


async def test_unexpected_task_is_rejected(wb, zoo):
    _, _, _, hook = await _setup(wb, zoo)
    status, d = await wb.receiver.receive(
        hook.id, _headers(hook), _status_update("someone-elses-task")
    )
    assert status == 400 and d.reasons == ["unexpected_task"]


async def test_duplicate_delivery_is_acknowledged_and_flagged(wb, zoo):
    _, conv, task_id, hook = await _setup(wb, zoo)
    body = _status_update(task_id)
    await wb.receiver.receive(hook.id, _headers(hook), body)
    status, d = await wb.receiver.receive(hook.id, _headers(hook), body)
    assert status == 200 and d.duplicate is True
    assert len([e for e in await wb.conversations.events(conv.id) if e.kind == "push"]) == 1


async def test_malformed_body_and_missing_token(wb, zoo):
    _, _, task_id, hook = await _setup(wb, zoo)
    status, d = await wb.receiver.receive(hook.id, _headers(hook), b"{not json")
    assert status == 400 and d.reasons == ["malformed"]
    status, d = await wb.receiver.receive(hook.id, _headers(hook), b'{"neither": 1}')
    assert status == 400 and d.reasons == ["malformed"]
    status, d = await wb.receiver.receive(
        hook.id, _headers(hook, token=False), _status_update(task_id)
    )
    assert status == 200 and any("token" in n for n in d.notes)


async def test_rate_limit(wb, zoo):
    _, _, task_id, hook = await _setup(wb, zoo)
    statuses = [
        (
            await wb.receiver.receive(
                hook.id, _headers(hook), _status_update(task_id, context_id=str(i))
            )
        )[0]
        for i in range(62)
    ]
    assert statuses[-1] == 429 and statuses[0] == 200


async def test_deliveries_never_store_secrets(wb, zoo):
    agent, _, task_id, hook = await _setup(wb, zoo)
    await wb.receiver.receive(hook.id, _headers(hook), _status_update(task_id))
    await wb.receiver.receive(
        hook.id, {**_headers(hook), "authorization": "Bearer guess"}, _status_update(task_id)
    )
    dump = json.dumps(
        [d.model_dump(mode="json") for d in await wb.receiver.deliveries(agent.id)],
        ensure_ascii=False,
    )
    assert hook.credentials not in dump and hook.token not in dump and "guess" not in dump
    assert "••••" in dump
