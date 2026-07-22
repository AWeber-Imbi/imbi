import asyncio
import os

import pytest


@pytest.fixture(scope='session', autouse=True)
def _initialize_graph() -> None:
    """Run graph schema initialization once per test session.

    Only runs when POSTGRES_URL is set so database-free suites (mcp,
    plugins) work without the docker stack.
    """
    if not os.environ.get('POSTGRES_URL'):
        return
    from imbi.common.graph.initializer import initialize

    asyncio.run(initialize())
