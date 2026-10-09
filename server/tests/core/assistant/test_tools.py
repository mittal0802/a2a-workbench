import pytest

from a2a_workbench.core.a2a_json import card_from_json, to_json
from a2a_workbench.core.assistant.tools import (
    CallRejected,
    SessionIds,
    build_tools,
    describe_agent,
    validate_call,
)


@pytest.fixture
async def zoo_agent(wb, zoo):
    return await wb.agents.add(zoo.base_url)


def _card(agent):
    return card_from_json(agent.card)


async def test_tool_description_uses_only_card_fields(zoo_agent):
    card = _card(zoo_agent)
    text = describe_agent(card)
    assert card.name in text and card.description in text
    for skill in card.skills:
        assert skill.id in text and skill.name in text and skill.description in text
        for example in skill.examples:
            assert example in text
    assert "text/plain" in text


async def test_tool_names_are_unique_slugs(zoo_agent):
    twin = zoo_agent.model_copy(update={"id": "other"})
    tools = build_tools([zoo_agent, twin])
    names = [t.spec.name for t in tools if t.agent_id]
    assert names == ["call_zoo_agent", "call_zoo_agent_2"]
    assert {t.spec.name for t in tools if not t.agent_id} == {"get_task", "cancel_task"}
    schema = tools[0].spec.input_schema
    assert schema["required"] == ["message"]
    assert set(schema["properties"]) == {
        "message",
        "data",
        "file_urls",
        "context_id",
        "task_id",
        "reference_task_ids",
        "accepted_output_modes",
    }
    assert "skill" not in str(schema).lower().replace("skills", "")


async def test_rejects_unknown_context_id(zoo_agent):
    with pytest.raises(CallRejected) as info:
        validate_call(
            _card(zoo_agent), zoo_agent.id, {"message": "hi", "context_id": "made-up"}, SessionIds()
        )
    assert info.value.rule == "context_not_issued" and "3.4.1" in info.value.spec_ref


async def test_rejects_unknown_task_id(zoo_agent):
    with pytest.raises(CallRejected) as info:
        validate_call(
            _card(zoo_agent), zoo_agent.id, {"message": "hi", "task_id": "t-404"}, SessionIds()
        )
    assert info.value.rule == "task_unknown" and "3.4.2" in info.value.spec_ref


async def test_terminal_task_needs_a_follow_up_with_references(zoo_agent):
    ids = SessionIds()
    ids.record(zoo_agent.id, "ctx1", "t1", "completed")
    with pytest.raises(CallRejected) as info:
        validate_call(
            _card(zoo_agent),
            zoo_agent.id,
            {"message": "more", "task_id": "t1", "context_id": "ctx1"},
            ids,
        )
    assert info.value.rule == "task_terminal"
    assert "reference_task_ids" in info.value.message and "Life of a Task" in info.value.spec_ref
    validate_call(
        _card(zoo_agent),
        zoo_agent.id,
        {"message": "more", "context_id": "ctx1", "reference_task_ids": ["t1"]},
        ids,
    )


async def test_mismatched_context_and_task_rejected(zoo_agent):
    ids = SessionIds()
    ids.record(zoo_agent.id, "ctx1", "t1", "input_required")
    ids.record(zoo_agent.id, "ctx2", None, None)
    with pytest.raises(CallRejected) as info:
        validate_call(
            _card(zoo_agent),
            zoo_agent.id,
            {"message": "B", "task_id": "t1", "context_id": "ctx2"},
            ids,
        )
    assert info.value.rule == "context_task_mismatch"


async def test_ids_of_another_agent_are_not_valid(zoo_agent):
    ids = SessionIds()
    ids.record("someone-else", "ctx1", "t1", "input_required")
    with pytest.raises(CallRejected):
        validate_call(_card(zoo_agent), zoo_agent.id, {"message": "B", "task_id": "t1"}, ids)


async def test_unknown_reference_rejected(zoo_agent):
    with pytest.raises(CallRejected) as info:
        validate_call(
            _card(zoo_agent),
            zoo_agent.id,
            {"message": "x", "reference_task_ids": ["nope"]},
            SessionIds(),
        )
    assert info.value.rule == "reference_unknown"


async def test_data_part_needs_a_json_input_mode(zoo_agent):
    card = _card(zoo_agent)
    validate_call(card, zoo_agent.id, {"message": "x", "data": {"n": 1}}, SessionIds())
    del card.default_input_modes[:]
    card.default_input_modes.append("text/plain")
    for skill in card.skills:
        del skill.input_modes[:]
    with pytest.raises(CallRejected) as info:
        validate_call(card, zoo_agent.id, {"message": "x", "data": {"n": 1}}, SessionIds())
    assert info.value.rule == "input_mode_not_declared"
    with pytest.raises(CallRejected):
        validate_call(
            card, zoo_agent.id, {"message": "x", "file_urls": ["https://e/f.png"]}, SessionIds()
        )


async def test_valid_continuation_passes(zoo_agent):
    ids = SessionIds()
    ids.record(zoo_agent.id, "ctx1", "t1", "input_required")
    validate_call(
        _card(zoo_agent), zoo_agent.id, {"message": "B", "task_id": "t1", "context_id": "ctx1"}, ids
    )
    validate_call(_card(zoo_agent), zoo_agent.id, {"message": "B", "task_id": "t1"}, ids)
    assert ids.context_of(zoo_agent.id, "t1") == "ctx1"
    assert to_json(_card(zoo_agent))
