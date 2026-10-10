"""The built-in checks, collected from ``core.health.checks``."""

from a2a_workbench.core.health.model import Check

_CHECKS: list[Check] = []


def register(check: Check) -> Check:
    """Add ``check`` to the built-in set (ids are unique)."""
    if any(c.id == check.id for c in _CHECKS):
        raise ValueError(f"duplicate check id {check.id}")
    _CHECKS.append(check)
    return check


def builtin_checks() -> list[Check]:
    """Every built-in check, in area order."""
    import a2a_workbench.core.health.checks  # noqa: F401 - registers on import

    return sorted(_CHECKS, key=lambda c: (c.area, c.id))
