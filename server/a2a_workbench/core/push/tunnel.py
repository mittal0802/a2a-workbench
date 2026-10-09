"""A Cloudflare quick tunnel that makes this server's webhooks reachable from the internet."""

import asyncio
import contextlib
import re
import shutil

_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class TunnelUnavailableError(RuntimeError):
    """``cloudflared`` is not installed, or did not print a tunnel URL in time."""


class Tunnel:
    """Runs ``cloudflared tunnel --url http://127.0.0.1:<port>`` and exposes its public URL."""

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable
        self._process: asyncio.subprocess.Process | None = None
        self.url: str | None = None
        self._drainer: asyncio.Future[None] | None = None

    @property
    def running(self) -> bool:
        """Whether the tunnel process is alive."""
        return self._process is not None and self._process.returncode is None

    async def start(self, port: int, *, timeout_s: float = 30) -> str:
        """Start the tunnel to ``port`` and return its ``https://…trycloudflare.com`` URL.

        Raises:
            TunnelUnavailableError: if cloudflared is missing or prints no URL in time.
        """
        if self.running and self.url:
            return self.url
        exe = self._executable or shutil.which("cloudflared")
        if not exe or not shutil.which(exe):
            raise TunnelUnavailableError(
                "cloudflared is not installed; install it, or set PUBLIC_BASE_URL to a URL "
                "that reaches this server"
            )
        self._process = await asyncio.create_subprocess_exec(
            exe,
            "tunnel",
            "--no-autoupdate",
            "--url",
            f"http://127.0.0.1:{port}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(timeout_s):
                assert self._process.stderr is not None
                while line := await self._process.stderr.readline():
                    if match := _URL.search(line.decode(errors="replace")):
                        self.url = match.group(0)
                        self._drainer = asyncio.ensure_future(self._drain())
                        return self.url
        except TimeoutError:
            pass
        await self.stop()
        raise TunnelUnavailableError("cloudflared did not report a tunnel URL")

    async def _drain(self) -> None:
        with contextlib.suppress(Exception):
            assert self._process is not None and self._process.stderr is not None
            while await self._process.stderr.readline():
                pass

    async def stop(self) -> None:
        """Stop the tunnel process (no-op when not running)."""
        process, self._process, self.url = self._process, None, None
        if process is not None and process.returncode is None:
            process.terminate()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(5):
                    await process.wait()
            if process.returncode is None:
                process.kill()
