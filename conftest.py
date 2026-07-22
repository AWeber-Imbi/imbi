import asyncio
import os
import pathlib
import sys

import pytest

# Test helpers import as rootdir-anchored namespace packages
# (apps.api.tests.support, libraries.common.tests.test_plugins.…), so
# the repository root must be importable during collection.
sys.path.insert(0, str(pathlib.Path(__file__).parent))


@pytest.fixture(scope='session', autouse=True)
def _initialize_graph() -> None:  # pyright: ignore[reportUnusedFunction]
    """Run graph schema initialization once per test session.

    Only runs when POSTGRES_URL is set so database-free suites (mcp,
    plugins) work without the docker stack.
    """
    if not os.environ.get('POSTGRES_URL'):
        return
    from imbi.common.graph.initializer import initialize

    asyncio.run(initialize())
