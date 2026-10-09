import subprocess
import sys
import time

import httpx

from a2a_workbench.fixtures.runner import free_port


def test_fixtures_serves_oauth_zoo_with_mock_idp():
    port, idp_port = free_port(), free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from a2a_workbench.cli.main import app; app()",
            "fixtures",
            "--port",
            str(port),
            "--no-grpc",
            "--auth",
            "oauth",
            "--idp-port",
            str(idp_port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        card = None
        for _ in range(300):
            try:
                card = httpx.get(f"http://127.0.0.1:{port}/.well-known/agent-card.json").json()
                break
            except (httpx.HTTPError, ValueError):
                time.sleep(0.1)
        assert card is not None
        meta = card["securitySchemes"]["oauthCode"]["oauth2SecurityScheme"]["oauth2MetadataUrl"]
        assert meta.startswith(f"http://127.0.0.1:{idp_port}")
        assert httpx.get(meta).json()["token_endpoint"] == f"http://127.0.0.1:{idp_port}/token"
    finally:
        proc.terminate()
        proc.wait(10)
