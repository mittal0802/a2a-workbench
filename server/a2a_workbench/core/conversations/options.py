"""Per-message send options and their mapping onto SDK request objects."""

from typing import Any

from a2a.client import ClientCallContext
from a2a.client.service_parameters import ServiceParametersFactory, with_a2a_extensions
from a2a.types import Message, SendMessageConfiguration, SendMessageRequest
from pydantic import BaseModel, Field


class SendOptions(BaseModel):
    """Every client-controllable aspect of a SendMessage / SendStreamingMessage call."""

    stream: bool = True
    return_immediately: bool = False
    accepted_output_modes: list[str] = Field(default_factory=list)
    history_length: int | None = Field(default=None, ge=0)
    extensions: list[str] = Field(default_factory=list)
    message_metadata: dict[str, Any] | None = None
    request_metadata: dict[str, Any] | None = None
    reference_task_ids: list[str] = Field(default_factory=list)
    task_id: str | None = None
    context_id: str | None = None
    interface_url: str | None = None


def build_request(message: Message, options: SendOptions) -> SendMessageRequest:
    """Return a ``SendMessageRequest`` for ``message`` configured by ``options``.

    Message-level fields (metadata, extensions, reference task ids) are set on a
    copy of ``message``; ``message`` itself is not modified.
    """
    msg = Message()
    msg.CopyFrom(message)
    if options.message_metadata:
        msg.metadata.update(options.message_metadata)
    msg.extensions.extend(options.extensions)
    msg.reference_task_ids.extend(options.reference_task_ids)
    config = SendMessageConfiguration(
        accepted_output_modes=options.accepted_output_modes,
        return_immediately=options.return_immediately,
    )
    if options.history_length is not None:
        config.history_length = options.history_length
    request = SendMessageRequest(message=msg, configuration=config)
    if options.request_metadata:
        request.metadata.update(options.request_metadata)
    return request


def build_call_context(options: SendOptions) -> ClientCallContext | None:
    """Return a call context that activates ``options.extensions``, or None."""
    if not options.extensions:
        return None
    params = ServiceParametersFactory.create([with_a2a_extensions(options.extensions)])
    return ClientCallContext(service_parameters=params)
