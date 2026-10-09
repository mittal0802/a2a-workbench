"""Server logging that keeps OAuth codes and tokens out of the access log."""

import copy
import logging
from typing import Any

from a2a_workbench.core.connection.recorder import REDACTED


class RedactOAuthQuery(logging.Filter):
    """Masks the query string of logged request paths under ``/oauth/``.

    Provider redirects carry the authorization code (and, for errors, free
    text) in the query string.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path, sep, _ = args[2].partition("?")
            if sep and path.startswith("/oauth/"):
                record.args = (*args[:2], f"{path}?{REDACTED}", *args[3:])
        return True


def log_config() -> dict[str, Any]:
    """Return uvicorn's default logging configuration with ``RedactOAuthQuery`` on access logs."""
    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["redact_oauth"] = {"()": RedactOAuthQuery}
    config["handlers"]["access"].setdefault("filters", []).append("redact_oauth")
    return config
