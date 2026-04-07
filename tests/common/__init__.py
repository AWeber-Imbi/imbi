"""Test utilities and base classes for imbi-common tests."""

import unittest


class AGETestCase(unittest.IsolatedAsyncioTestCase):
    """Base class for tests requiring AGE connection.

    This class automatically handles:
    - Initializing AGE connection before each test
    - Cleaning up test data after each test
    - Closing AGE connection after each test
    """

    async def asyncSetUp(self):
        """Initialize AGE connection before each test."""
        from imbi_common import age

        await age.initialize()

    async def asyncTearDown(self):
        """Clean up test data and close connection after each test."""
        from imbi_common import age

        await age.query('MATCH (n) DETACH DELETE n RETURN count(n) AS deleted')
        await age.aclose()


class ClickHouseTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class for tests requiring ClickHouse connection.

    This class automatically handles:
    - Initializing ClickHouse connection before each test
    - Setting up schema before each test
    """

    async def asyncSetUp(self):
        """Initialize ClickHouse connection and schema before each test."""
        from imbi_common import clickhouse

        await clickhouse.initialize()
        await clickhouse.setup_schema()
