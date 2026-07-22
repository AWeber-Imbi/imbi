import asyncio

import pytest

from imbi_common.graph.initializer import initialize


@pytest.fixture(scope='session', autouse=True)
def _initialize_graph() -> None:
    """Run graph schema initialization once per test session."""
    asyncio.run(initialize())
