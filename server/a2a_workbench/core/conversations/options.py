"""Per-message send options and their mapping onto SDK request objects."""

from typing import Any

from a2a.client import ClientCallContext
from a2a.client.service_parameters import ServiceParametersFactory, with_a2a_extensions
from a2a.types import Message, SendMessageConfiguration, SendMessageRequest
from pydantic import BaseModel, Field

from a2a_workbench.core.faults.profile import FaultProfile


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
    faults: FaultProfile | None = None
    skill_id: str | None = None
    """Skill whose card-declared security requirements choose the credentials.

    Never sent: A2A messages have no skill field, and the agent decides which
    skill handles a request.
    """
    inherit_ids: bool = True
    """Fill in the conversation's context id and open task id when the options omit them.

    With False, the message carries exactly ``context_id`` and ``task_id`` as given.
    """


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


def build_call_context(
    options: SendOptions | None = None, headers: dict[str, str] | None = None
) -> ClientCallContext | None:
    """Return a call context carrying ``headers`` and activating the options' extensions.

    Returns None when there is nothing to send.
    """
    extensions = options.extensions if options else []
    if not extensions and not headers:
        return None
    params = dict(headers or {})
    if extensions:
        params = ServiceParametersFactory.create_from(params, [with_a2a_extensions(extensions)])
    return ClientCallContext(service_parameters=params)
