"""Test utilities and base classes for imbi-common tests."""

import os
import unittest


class Neo4jTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class for tests requiring Neo4j connection.

    This class automatically handles:
    - Skipping tests when SKIP_INTEGRATION_TESTS is set
    - Initializing Neo4j connection before each test
    - Cleaning up test data after each test
    - Closing Neo4j connection after each test
    """

    @classmethod
    def setUpClass(cls):
        """Skip all tests in this class if integration tests disabled."""
        if os.environ.get('SKIP_INTEGRATION_TESTS'):
            raise unittest.SkipTest('Integration tests disabled')

    async def asyncSetUp(self):
        """Initialize Neo4j connection before each test."""
        from imbi_common import neo4j

        await neo4j.initialize()

    async def asyncTearDown(self):
        """Clean up test data and close connection after each test."""
        from imbi_common import neo4j

        await neo4j.execute_write('MATCH (n) DETACH DELETE n')
        await neo4j.aclose()


class ClickHouseTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class for tests requiring ClickHouse connection.

    This class automatically handles:
    - Skipping tests when SKIP_INTEGRATION_TESTS is set
    - Initializing ClickHouse connection before each test
    - Setting up schema before each test
    """

    @classmethod
    def setUpClass(cls):
        """Skip all tests in this class if integration tests disabled."""
        if os.environ.get('SKIP_INTEGRATION_TESTS'):
            raise unittest.SkipTest('Integration tests disabled')

    async def asyncSetUp(self):
        """Initialize ClickHouse connection and schema before each test."""
        from imbi_common import clickhouse

        await clickhouse.initialize()
        await clickhouse.setup_schema()
