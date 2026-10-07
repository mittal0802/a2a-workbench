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


async def test_each_exchange_is_recorded_once():
    sink = Collector()
    async with _client(lambda r: httpx.Response(200, json={}), sink) as c:
        r = await c.get("http://x/")
        await r.aclose()
    assert len(sink.items) == 1
