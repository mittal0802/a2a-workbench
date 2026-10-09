import stat

import pytest

from a2a_workbench.core.push.tunnel import Tunnel, TunnelUnavailableError


@pytest.fixture
def fake_cloudflared(tmp_path):
    script = tmp_path / "cloudflared"
    script.write_text(
        "#!/bin/sh\n"
        "echo 'INF Requesting new quick Tunnel on trycloudflare.com...' 1>&2\n"
        "echo 'INF |  https://sunny-river-1234.trycloudflare.com                |' 1>&2\n"
        "sleep 30\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


async def test_tunnel_reports_the_public_url_and_stops(fake_cloudflared):
    tunnel = Tunnel(executable=fake_cloudflared)
    url = await tunnel.start(8484, timeout_s=5)
    assert (
        url == "https://sunny-river-1234.trycloudflare.com" and tunnel.url == url and tunnel.running
    )
    await tunnel.stop()
    assert not tunnel.running and tunnel.url is None


async def test_missing_cloudflared_is_reported(tmp_path):
    with pytest.raises(TunnelUnavailableError) as info:
        await Tunnel(executable=str(tmp_path / "nope")).start(8484)
    assert "cloudflared" in str(info.value)
