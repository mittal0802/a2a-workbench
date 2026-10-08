import time

import httpx
import pytest

from a2a_workbench.core.connection.recorder import RecordingTransport, recording_scope
from a2a_workbench.core.faults.http import FaultTransport
from a2a_workbench.core.faults.injector import FaultInjector
from a2a_workbench.core.faults.profile import FaultProfile, FaultRule

SSE = b"".join(f'data: {{"n":{i}}}\n\n'.encode() for i in range(5))


def _sse(_request):
    return httpx.Response(200, content=SSE, headers={"content-type": "text/event-stream"})


def _client(rule, handler=_sse, sink=None):
    inner = httpx.MockTransport(handler)
    ft = FaultTransport(inner, FaultInjector(FaultProfile(rules=[rule])), binding="JSONRPC")
    return httpx.AsyncClient(transport=RecordingTransport(sink, ft) if sink is not None else ft)


class Sink(list):
    async def __call__(self, ex):
        self.append(ex)


@pytest.mark.parametrize(
    "kind,exc",
    [
        ("refuse", httpx.ConnectError),
        ("dns_fail", httpx.ConnectError),
        ("tls_fail", httpx.ConnectError),
        ("connect_timeout", httpx.ConnectTimeout),
        ("read_timeout", httpx.ReadTimeout),
    ],
)
async def test_connection_faults_raise(kind, exc):
    async with _client(FaultRule(kind=kind)) as c:
        with pytest.raises(exc):
            await c.get("http://x/")


async def test_drop_stream_after_events():
    got = b""
    async with _client(FaultRule(kind="drop_stream", params={"after_events": 2})) as c:
        with pytest.raises(httpx.ReadError):
            async with c.stream("POST", "http://x/") as r:
                async for chunk in r.aiter_bytes():
                    got += chunk
    assert got.count(b"\n\n") == 2


async def test_drop_stream_after_zero_events_drops_immediately():
    async with _client(FaultRule(kind="drop_stream", params={"after_events": 0})) as c:
        with pytest.raises(httpx.ReadError):
            await c.get("http://x/")


async def test_reset_breaks_the_body():
    async with _client(FaultRule(kind="reset")) as c:
        with pytest.raises(httpx.ReadError):
            await c.get("http://x/")


async def test_http_status_short_circuits():
    async with _client(FaultRule(kind="http_status", params={"code": 429, "retry_after": 3})) as c:
        r = await c.get("http://x/")
    assert r.status_code == 429 and r.headers["retry-after"] == "3"


async def test_truncate_and_garble_change_bytes():
    async with _client(FaultRule(kind="truncate", params={"bytes": 4})) as c:
        assert len((await c.get("http://x/")).content) == 4
    async with _client(FaultRule(kind="garble")) as c:
        body = (await c.get("http://x/")).content
    assert body != SSE and len(body) == len(SSE)


async def test_delay_then_forward():
    async with _client(FaultRule(kind="delay", params={"ms": 50})) as c:
        start = time.monotonic()
        r = await c.get("http://x/")
    assert r.status_code == 200 and time.monotonic() - start >= 0.05


async def test_expire_token_returns_401_with_challenge():
    async with _client(FaultRule(kind="expire_token")) as c:
        r = await c.get("http://x/")
    assert r.status_code == 401 and "invalid_token" in r.headers["www-authenticate"]


async def test_injected_fault_is_labelled_in_recording():
    sink = Sink()
    async with _client(FaultRule(kind="refuse"), sink=sink) as c:
        with recording_scope("send_message"), pytest.raises(httpx.ConnectError):
            await c.get("http://x/")
    assert sink[0].fault == "refuse"


async def test_operation_from_scope_drives_matching():
    rule = FaultRule.model_validate({"kind": "refuse", "match": {"operation": "get_task"}})
    async with _client(rule) as c:
        with recording_scope("send_message"):
            assert (await c.get("http://x/")).status_code == 200
        with recording_scope("get_task"), pytest.raises(httpx.ConnectError):
            await c.get("http://x/")


async def test_no_fault_passes_through_untouched():
    async with _client(FaultRule(kind="refuse", match={"operation": "never"})) as c:
        assert (await c.get("http://x/")).content == SSE
