import pytest

from a2a_workbench.core.blobs import BlobNotFoundError, BlobTooLargeError


async def test_put_and_lookup(wb):
    out = await wb.blobs.put(b"abc", "text/plain", "a.txt")
    assert out.size == 3
    assert await wb.blobs.lookup(out.id) == (b"abc", "text/plain", "a.txt")


async def test_empty_media_type_defaults_to_octet_stream(wb):
    out = await wb.blobs.put(b"x", "", None)
    assert out.media_type == "application/octet-stream"


async def test_too_large(wb):
    wb.blobs.max_bytes = 2
    with pytest.raises(BlobTooLargeError):
        await wb.blobs.put(b"abc", "text/plain", None)


async def test_missing(wb):
    with pytest.raises(BlobNotFoundError):
        await wb.blobs.lookup("nope")
