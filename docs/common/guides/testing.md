# Testing Guide

This guide covers testing applications that use imbi-common.

## Overview

Testing with imbi-common involves:

1. **Unit Tests**: Test logic without external dependencies
2. **Integration Tests**: Test with real databases (Docker)
3. **Mocking**: Mock database clients for isolated testing

## Test Framework

The tests are written with the standard `unittest` classes
(`unittest.TestCase` and `unittest.IsolatedAsyncioTestCase`). pytest runs
them, with `pytest-cov` for coverage. Do not use pytest fixtures or
pytest-style test functions.

### Basic Test Structure

```python
import unittest
from imbi.common import settings

class TestSettings(unittest.TestCase):
    def test_default_postgres_url(self):
        config = settings.Postgres()
        self.assertIn("localhost", str(config.url))
        self.assertEqual(config.graph_name, "imbi")

    def test_default_pool_sizes(self):
        config = settings.Postgres()
        self.assertEqual(config.min_pool_size, 2)
        self.assertEqual(config.max_pool_size, 10)
```

### Async Test Cases

For async functions, use `IsolatedAsyncioTestCase`:

```python
import unittest
from imbi.common import graph, models

class TestGraphOperations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = graph.Graph()
        await self.db.open()

    async def asyncTearDown(self):
        await self.db.close()

    async def test_create_node(self):
        org = models.Organization(
            name="Test Org",
            slug="test-org",
            description="Test",
        )
        created = await self.db.create(org)
        self.assertEqual(created.name, "Test Org")

        # Cleanup
        await self.db.delete(org)
```

## Unit Tests

Unit tests should not require external dependencies.

### Testing Settings

```python
import unittest
from imbi.common import settings

class TestSettings(unittest.TestCase):
    def test_postgres_defaults(self):
        config = settings.Postgres()
        self.assertEqual(config.graph_name, "imbi")
        self.assertEqual(config.min_pool_size, 2)
        self.assertEqual(config.max_pool_size, 10)

    def test_clickhouse_defaults(self):
        config = settings.Clickhouse()
        self.assertIn("localhost", str(config.url))
```

### Testing Models

```python
import unittest
from imbi.common import models

class TestModels(unittest.TestCase):
    def test_blueprint_slug_generation(self):
        blueprint = models.Blueprint(
            name="Cloud Provider",
            type="Project",
            json_schema={"type": "object", "properties": {}}
        )
        self.assertEqual(blueprint.slug, "cloud-provider")
```

### Testing Auth Functions

```python
import unittest
from imbi.common.auth import core

class TestAuth(unittest.TestCase):
    def test_jwt_creation_and_verification(self):
        token = core.create_access_token(
            subject="user@example.com",
            extra_claims={"role": "admin"}
        )

        # Verify token
        payload = core.verify_token(token)
        self.assertEqual(payload["sub"], "user@example.com")
        self.assertEqual(payload["role"], "admin")

    def test_refresh_token(self):
        token = core.create_refresh_token(
            subject="user@example.com"
        )
        payload = core.verify_token(token)
        self.assertEqual(payload["sub"], "user@example.com")
        self.assertEqual(payload["type"], "refresh")
```

### Testing Logging

```python
import unittest
from imbi.common import logging

class TestLogging(unittest.TestCase):
    def test_get_log_config(self):
        config = logging.get_log_config()
        self.assertIsInstance(config, dict)

    def test_configure_logging_dev_mode(self):
        # Should not raise
        logging.configure_logging(dev=True)
```

## Integration Tests

Integration tests require Docker services. Start them with
`moon run root:services` before you run the tests.

```python
import unittest
from imbi.common import graph

class TestGraphIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = graph.Graph()
        await self.db.open()

    async def asyncTearDown(self):
        await self.db.close()

    async def test_database_connection(self):
        # execute() wraps the query in AGE cypher(), so use Cypher, not SQL
        rows = await self.db.execute("RETURN 1", columns=["status"])
        self.assertEqual(len(rows), 1)
```

### Docker Compose for Tests

Start the test services. This command starts `compose.ci.yaml` and writes
the service ports to `.env.test`:

```bash
moon run root:services
```

Run tests:

```bash
moon run common:test
```

## Mocking

Mock database clients for isolated testing.

### Mocking the Graph Client

```python
import unittest
from unittest.mock import AsyncMock, MagicMock
from imbi.common import graph, models

class TestServiceLogic(unittest.IsolatedAsyncioTestCase):
    async def test_get_organization(self):
        mock_db = MagicMock(spec=graph.Graph)
        mock_org = models.Organization(
            name="Mocked Org",
            slug="mocked-org",
            description="Test",
        )
        mock_db.match = AsyncMock(return_value=[mock_org])

        results = await mock_db.match(
            models.Organization,
            {"slug": "mocked-org"},
        )

        self.assertEqual(results[0].name, "Mocked Org")
        mock_db.match.assert_called_once()
```

### Mocking ClickHouse

```python
import unittest
from unittest.mock import AsyncMock, patch

class TestAnalytics(unittest.IsolatedAsyncioTestCase):
    @patch('imbi.common.clickhouse.query')
    async def test_query_analytics(self, mock_query):
        mock_query.return_value = [
            {"project_id": "project1", "count": 10},
            {"project_id": "project2", "count": 5}
        ]

        from imbi.common import clickhouse

        results = await clickhouse.query(
            "SELECT project_id, COUNT(*) AS count "
            "FROM commits FINAL GROUP BY project_id"
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["project_id"], "project1")
```

## Running Tests

### Run All Tests

```bash
moon run common:test
```

`moon run common:test` starts the services first (`root:services`).

Run the other commands below from the repository root, after
`moon run root:services` has written `.env.test`.

### Run Specific Test File

```bash
uv run --frozen --env-file .env.test pytest libraries/common/tests/test_settings.py
```

### Run Specific Test Method

```bash
uv run --frozen --env-file .env.test pytest \
  libraries/common/tests/test_settings.py::PostgresSettingsTestCase::test_default_settings
```

### Run with Verbose Output

```bash
uv run --frozen --env-file .env.test pytest -v libraries/common/tests
```

## Continuous Integration

CI runs `moon ci` in `.github/workflows/test.yml`. Use that workflow as
the reference for how CI starts the services and runs the tests.

## Test Coverage

Track test coverage with `coverage` (via `moon run root:coverage`):

```bash
# Run the full suite with aggregate coverage (requires Docker)
moon run root:coverage

# Run a specific file
uv run --env-file .env.test pytest libraries/common/tests/test_settings.py
```

The coverage configuration is in `libraries/common/pyproject.toml`,
under `[tool.coverage.run]` and `[tool.coverage.report]`. It measures
`imbi.common` (`source_pkgs`), with branch coverage, and fails under
85%. `moon run common:test` passes this file to pytest-cov with
`--cov-config`. There is no `.coveragerc` file.

## Best Practices

1. **Isolate Tests**: Each test should be independent
2. **Clean Up**: Always clean up test data in `tearDown`/`asyncTearDown`
3. **Use Fixtures**: Create reusable test data with fixtures
4. **Mock External Services**: Don't hit real APIs in unit tests
5. **Test Edge Cases**: Test error conditions and boundary cases
6. **Fast Unit Tests**: Keep unit tests fast by avoiding I/O
7. **Clear Test Names**: Use descriptive test method names
8. **One Assert Per Test**: Focus each test on one behavior
