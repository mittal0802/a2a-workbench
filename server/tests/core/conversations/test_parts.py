import base64

import pytest
from pydantic import TypeAdapter, ValidationError

from a2a_workbench.core.conversations.parts import PartInput, build_part

adapter = TypeAdapter(PartInput)


async def _blobs(blob_id):
    return b"\x89PNG", "image/png", "p.png"


async def test_text_part():
    p = await build_part(
        adapter.validate_python({"kind": "text", "text": "hi", "metadata": {"k": 1}}), _blobs
    )
    assert p.text == "hi" and p.metadata["k"] == 1


async def test_file_part_from_blob_is_raw():
    p = await build_part(adapter.validate_python({"kind": "file", "blob_id": "b1"}), _blobs)
    assert p.raw == b"\x89PNG" and p.media_type == "image/png" and p.filename == "p.png"


async def test_file_part_from_url():
    p = await build_part(
        adapter.validate_python(
            {"kind": "file", "url": "https://x/y.pdf", "media_type": "application/pdf"}
        ),
        _blobs,
    )
    assert p.url == "https://x/y.pdf" and p.media_type == "application/pdf"


async def test_file_part_inline_base64():
    p = await build_part(
        adapter.validate_python(
            {
                "kind": "file",
                "raw_base64": base64.b64encode(b"ab").decode(),
                "media_type": "text/plain",
            }
        ),
        _blobs,
    )
    assert p.raw == b"ab"


async def test_data_part():
    p = await build_part(adapter.validate_python({"kind": "data", "data": {"a": [1, 2]}}), _blobs)
    assert p.data.struct_value.fields["a"].list_value.values[1].number_value == 2


async def test_scalar_data_part():
    p = await build_part(adapter.validate_python({"kind": "data", "data": 5}), _blobs)
    assert p.data.number_value == 5


def test_file_part_requires_exactly_one_source():
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "file"})
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "file", "url": "u", "blob_id": "b"})


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "video"})
