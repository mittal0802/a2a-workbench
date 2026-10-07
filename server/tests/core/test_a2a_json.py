from a2a.types import AgentCard, Part, TaskState

from a2a_workbench.core.a2a_json import (
    INTERRUPTED_STATES,
    TERMINAL_STATES,
    card_from_json,
    state_name,
    to_json,
)


def test_state_names_cover_every_task_state():
    names = {state_name(v) for v in TaskState.values()}
    assert names == {
        "unspecified",
        "submitted",
        "working",
        "completed",
        "failed",
        "canceled",
        "input_required",
        "rejected",
        "auth_required",
    }


def test_terminal_and_interrupted_sets():
    assert TERMINAL_STATES == {"completed", "failed", "canceled", "rejected"}
    assert INTERRUPTED_STATES == {"input_required", "auth_required"}


def test_to_json_uses_camel_case():
    assert to_json(Part(text="hi", media_type="text/plain")) == {
        "text": "hi",
        "mediaType": "text/plain",
    }


def test_card_round_trip():
    card = AgentCard(name="a", description="d", version="1")
    assert card_from_json(to_json(card)) == card


def test_card_from_json_ignores_unknown_fields():
    assert card_from_json({"name": "a", "futureField": 1}).name == "a"
