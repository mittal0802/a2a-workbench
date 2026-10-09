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


def test_fixtures_serves_the_scripted_llm():
    port = free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from a2a_workbench.cli.main import app; app()",
            "fixtures",
            "--llm",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(300):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/ready").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        r = httpx.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            headers={"authorization": "Bearer x"},
            json={"model": "scripted", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.json()["choices"][0]["message"]["content"] == "No agents."
    finally:
        proc.terminate()
        proc.wait(10)
