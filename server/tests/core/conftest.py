import pytest

from a2a_workbench.core.config import Settings
from a2a_workbench.core.workbench import Workbench


@pytest.fixture
async def wb():
    async with Workbench.open(Settings()) as workbench:
        yield workbench
