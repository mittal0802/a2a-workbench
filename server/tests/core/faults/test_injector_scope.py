from a2a_workbench.core.conversations.options import SendOptions
from a2a_workbench.core.conversations.parts import TextPartInput
from a2a_workbench.core.faults.profile import FaultMatch, FaultProfile, FaultRule


async def _send(wb, conv_id, text, faults):
    return [
        e
        async for e in wb.conversations.send(
            conv_id, [TextPartInput(text=text)], SendOptions(stream=False, faults=faults)
        )
    ]


async def test_once_rule_fires_only_on_first_message_of_a_conversation(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    profile = FaultProfile(rules=[FaultRule(kind="refuse")])
    first = await _send(wb, conv.id, "echo 1", profile)
    second = await _send(wb, conv.id, "echo 2", profile)
    assert first[-1].kind == "error"
    assert second[-1].data.get("state") == "completed"


async def test_nth_call_counts_across_messages(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    profile = FaultProfile(
        rules=[FaultRule(kind="refuse", match=FaultMatch(operation="send_message", nth_call=2))]
    )
    results = [(await _send(wb, conv.id, f"echo {i}", profile))[-1].kind for i in range(3)]
    assert results == ["task", "error", "task"]


async def test_probability_is_seeded_across_messages(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)

    async def run(seed):
        conv = await wb.conversations.create(agent.id)
        profile = FaultProfile(
            seed=seed, rules=[FaultRule(kind="refuse", mode="probability", probability=0.5)]
        )
        return [
            (await _send(wb, conv.id, f"echo {i}", profile))[-1].kind == "error" for i in range(12)
        ]

    a, b = await run(3), await run(3)
    assert a == b and any(a) and not all(a)


async def test_changing_the_profile_starts_fresh(wb, zoo):
    agent = await wb.agents.add(zoo.base_url)
    conv = await wb.conversations.create(agent.id)
    await _send(wb, conv.id, "echo 1", FaultProfile(rules=[FaultRule(kind="refuse")]))
    other = FaultProfile(name="other", rules=[FaultRule(kind="refuse")])
    assert (await _send(wb, conv.id, "echo 2", other))[-1].kind == "error"
