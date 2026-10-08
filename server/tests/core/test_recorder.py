import gzip
import json

import httpx
import pytest

from a2a_workbench.core.connection.recorder import (
    Exchange,
    RecordingTransport,
    recording_scope,
)


class Collector:
    def __init__(self):
        self.items: list[Exchange] = []

    async def __call__(self, ex: Exchange) -> None:
        self.items.append(ex)


def _client(handler, sink, **kw):
    return httpx.AsyncClient(transport=RecordingTransport(sink, httpx.MockTransport(handler), **kw))


async def test_records_json_request_and_response_with_redaction():
    sink = Collector()

    def handler(req):
        return httpx.Response(200, json={"ok": True})

    async with _client(handler, sink) as c:
        with recording_scope("send_message", agent_id="a1", conversation_id="c1") as scope:
            await c.post("http://x/a2a", json={"m": 1}, headers={"Authorization": "Bearer s3cret"})
    ex = sink.items[0]
    assert scope.exchange_ids == [ex.id]
    assert (ex.operation, ex.agent_id, ex.conversation_id) == ("send_message", "a1", "c1")
    assert ex.request_headers["authorization"] == "••••"
    assert "s3cret" not in json.dumps(ex.to_record())
    assert json.loads(ex.request_body) == {"m": 1}
    assert ex.status == 200 and json.loads(ex.response_body) == {"ok": True}
    assert ex.duration_ms is not None and ex.error is None


async def test_records_sse_frames_in_order():
    sink = Collector()
    body = b'data: {"a":1}\n\ndata: {"a":2}\n\n'

    def handler(req):
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    async with _client(handler, sink) as c, c.stream("POST", "http://x/a2a", json={}) as r:
        async for _ in r.aiter_bytes():
            pass
    assert [f.data for f in sink.items[0].frames] == ['data: {"a":1}', 'data: {"a":2}']
    assert sink.items[0].response_body is None


async def test_recording_transport_decodes_gzip_body():
    sink = Collector()

    def handler(req):
        return httpx.Response(
            200,
            content=gzip.compress(b'{"z":1}'),
            headers={"content-encoding": "gzip", "content-type": "application/json"},
        )

    async with _client(handler, sink) as c:
        r = await c.get("http://x/card")
    assert r.json() == {"z": 1}
    assert sink.items[0].response_body == '{"z":1}'


async def test_truncates_large_bodies():
    sink = Collector()

    def handler(req):
        return httpx.Response(200, content=b"x" * 100)

    async with _client(handler, sink, max_body_bytes=10) as c:
        await c.get("http://x/")
    assert sink.items[0].truncated is True
    assert len(sink.items[0].response_body) == 10


async def test_transport_error_is_recorded_and_reraised():
    sink = Collector()

    def handler(req):
        raise httpx.ConnectError("refused")

    async with _client(handler, sink) as c:
        with pytest.raises(httpx.ConnectError):
            await c.get("http://x/")
    assert sink.items[0].error.startswith("ConnectError")
    assert sink.items[0].status is None


async def test_without_scope_operation_is_http():
    sink = Collector()
    async with _client(lambda r: httpx.Response(204), sink) as c:
        await c.get("http://x/")
    assert sink.items[0].operation == "http"


async def test_each_exchange_is_completed_once():
    completions = []

    async def sink(ex):
        if ex.complete:
            completions.append(ex.id)

    async with httpx.AsyncClient(
        transport=RecordingTransport(
            sink, httpx.MockTransport(lambda r: httpx.Response(200, json={}))
        )
    ) as c:
        r = await c.get("http://x/")
        await r.aclose()
    assert len(completions) == 1


async def test_raw_deflate_body_still_reaches_caller_and_is_recorded():
    import zlib

    sink = Collector()
    raw = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    body = raw.compress(b'{"d":1}') + raw.flush()

    def handler(req):
        return httpx.Response(200, content=body, headers={"content-encoding": "deflate"})

    async with _client(handler, sink) as c:
        r = await c.get("http://x/")
    assert r.json() == {"d": 1}
    assert sink.items[0].response_body == '{"d":1}'


class RawTransport(httpx.AsyncBaseTransport):
    """Returns undecoded bytes, as a real network transport does."""

    def __init__(self, body, headers):
        self.body, self.headers = body, headers

    async def handle_async_request(self, request):
        return httpx.Response(200, headers=self.headers, stream=httpx.ByteStream(self.body))


async def test_corrupt_gzip_fails_the_caller_exactly_like_plain_httpx():
    headers = {"content-encoding": "gzip"}
    async with httpx.AsyncClient(transport=RawTransport(b"not gzip", headers)) as plain:
        with pytest.raises(httpx.DecodingError):
            await plain.get("http://x/")
    sink = Collector()
    transport = RecordingTransport(sink, RawTransport(b"not gzip", headers))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(httpx.DecodingError):
            await c.get("http://x/")
    assert "could not be decoded" in sink.items[0].response_body


async def test_raw_deflate_over_raw_transport():
    import zlib

    raw = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    body = raw.compress(b'{"d":2}') + raw.flush()
    sink = Collector()
    transport = RecordingTransport(sink, RawTransport(body, {"content-encoding": "deflate"}))
    async with httpx.AsyncClient(transport=transport) as c:
        assert (await c.get("http://x/")).json() == {"d": 2}
    assert sink.items[0].response_body == '{"d":2}'


async def test_stream_is_announced_at_start_and_completed_at_close():
    snapshots = []

    async def sink(ex):
        snapshots.append((ex.complete, len(ex.frames), ex.status))

    body = b'data: {"a":1}\n\ndata: {"a":2}\n\n'

    def handler(req):
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(
        transport=RecordingTransport(sink, httpx.MockTransport(handler))
    ) as c:
        async with c.stream("POST", "http://x/a2a", json={}) as r:
            assert snapshots == [(False, 0, 200)]
            async for _ in r.aiter_bytes():
                pass
    assert snapshots[-1] == (True, 2, 200)
