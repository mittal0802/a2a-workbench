"""Health checks by A2A area; importing this package registers them."""

from a2a_workbench.core.health.checks import (  # noqa: F401
    discovery,
    errors,
    extensions,
    messaging,
    push,
    resilience,
    security,
    streaming,
    tasks,
    transport,
)
