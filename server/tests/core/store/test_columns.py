from sqlalchemy import String

from a2a_workbench.core.store.models import Base

# Bounded columns may only hold values the Workbench generates itself.
INTERNAL = {
    "id",
    "workspace_id",
    "agent_id",
    "conversation_id",
    "exchange_id",
    "session_id",
    "kind",
    "status",
    "origin",
    "provider",
    "response_mode",
    "signature_status",
    "credentials_hash",
    "auth_scheme",
    "task_state",
}


def test_bounded_columns_hold_only_internal_values():
    offenders = [
        f"{t.name}.{c.name}"
        for t in Base.metadata.sorted_tables
        for c in t.columns
        if isinstance(c.type, String) and c.type.length and c.name not in INTERNAL
    ]
    assert offenders == []
