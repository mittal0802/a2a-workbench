"""User-supplied message parts and their conversion to A2A ``Part`` objects."""

import base64
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from a2a.types import Part
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Value
from pydantic import BaseModel, Field, model_validator

BlobLookup = Callable[[str], Awaitable[tuple[bytes, str, str | None]]]


class TextPartInput(BaseModel):
    """A text part."""

    kind: Literal["text"] = "text"
    text: str
    media_type: str | None = None
    metadata: dict[str, Any] | None = None


class FilePartInput(BaseModel):
    """A file given by uploaded blob id, inline base64 bytes, or URL (exactly one)."""

    kind: Literal["file"] = "file"
    blob_id: str | None = None
    raw_base64: str | None = None
    url: str | None = None
    media_type: str | None = None
    filename: str | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> "FilePartInput":
        if sum(v is not None for v in (self.blob_id, self.raw_base64, self.url)) != 1:
            raise ValueError("exactly one of blob_id, raw_base64 or url is required")
        return self


class DataPartInput(BaseModel):
    """A structured JSON data part."""

    kind: Literal["data"] = "data"
    data: Any
    media_type: str | None = None
    metadata: dict[str, Any] | None = None


AnyPartInput = TextPartInput | FilePartInput | DataPartInput
PartInput = Annotated[AnyPartInput, Field(discriminator="kind")]


async def build_part(part: AnyPartInput, blobs: BlobLookup) -> Part:
    """Return the A2A ``Part`` for ``part``, loading uploaded bytes through ``blobs``."""
    out = Part()
    if part.metadata:
        out.metadata.update(part.metadata)
    if isinstance(part, TextPartInput):
        out.text = part.text
        if part.media_type:
            out.media_type = part.media_type
        return out
    if isinstance(part, DataPartInput):
        out.data.CopyFrom(ParseDict(part.data, Value()))
        if part.media_type:
            out.media_type = part.media_type
        return out
    media_type, filename = part.media_type, part.filename
    if part.blob_id is not None:
        raw, blob_type, blob_name = await blobs(part.blob_id)
        out.raw = raw
        media_type, filename = media_type or blob_type, filename or blob_name
    elif part.raw_base64 is not None:
        out.raw = base64.b64decode(part.raw_base64)
    else:
        out.url = part.url or ""
    if media_type:
        out.media_type = media_type
    if filename:
        out.filename = filename
    return out
