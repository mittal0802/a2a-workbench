"""FastAPI dependencies."""

from fastapi import Request

from a2a_workbench.core.workbench import Workbench


def get_workbench(request: Request) -> Workbench:
    """Return the Workbench owned by the running application."""
    workbench: Workbench = request.app.state.workbench
    return workbench
