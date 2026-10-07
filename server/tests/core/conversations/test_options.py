from a2a.types import Message

from a2a_workbench.core.conversations.options import (
    SendOptions,
    build_call_context,
    build_request,
)


def test_defaults_leave_optional_fields_unset():
    req = build_request(Message(message_id="m"), SendOptions())
    assert not req.configuration.HasField("history_length")
    assert req.configuration.return_immediately is False
    assert list(req.configuration.accepted_output_modes) == []
    assert build_call_context(SendOptions()) is None


def test_every_option_is_mapped():
    opts = SendOptions(
        return_immediately=True,
        accepted_output_modes=["text/plain"],
        history_length=3,
        extensions=["https://e/1", "https://e/2"],
        message_metadata={"a": 1},
        request_metadata={"b": 2},
        reference_task_ids=["t0"],
    )
    message = Message(message_id="m")
    req = build_request(message, opts)
    assert req.configuration.history_length == 3
    assert req.configuration.return_immediately is True
    assert list(req.configuration.accepted_output_modes) == ["text/plain"]
    assert req.message.metadata["a"] == 1 and req.metadata["b"] == 2
    assert list(req.message.reference_task_ids) == ["t0"]
    assert list(req.message.extensions) == ["https://e/1", "https://e/2"]
    assert not message.extensions
    ctx = build_call_context(opts)
    assert ctx.service_parameters["A2A-Extensions"] == "https://e/1,https://e/2"


def test_history_length_zero_is_sent():
    req = build_request(Message(message_id="m"), SendOptions(history_length=0))
    assert req.configuration.HasField("history_length")
