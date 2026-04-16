# Testing Guide

This guide covers testing applications that use imbi-common.

## Overview

Testing with imbi-common involves:

1. **Unit Tests**: Test logic without external dependencies
2. **Integration Tests**: Test with real databases (Docker)
3. **Mocking**: Mock database clients for isolated testing

## Test Framework

imbi-common uses Python's standard `unittest` framework (not pytest).

### Basic Test Structure

```python
import unittest
from imbi_common import settings

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
from imbi_common import graph, models

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
from imbi_common import settings

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
from imbi_common import models

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
from imbi_common.auth import core

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
from imbi_common import logging

class TestLogging(unittest.TestCase):
    def test_get_log_config(self):
        config = logging.get_log_config()
        self.assertIsInstance(config, dict)

    def test_configure_logging_dev_mode(self):
        # Should not raise
        logging.configure_logging(dev=True)
```

## Integration Tests

Integration tests require Docker services.

### Environment Variable Control

Skip integration tests when databases are unavailable:

```python
import os
import unittest
from imbi_common import graph, models

@unittest.skipIf(
    os.environ.get('SKIP_INTEGRATION_TESTS'),
    "Skipping integration tests (SKIP_INTEGRATION_TESTS set)"
)
class TestGraphIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = graph.Graph()
        await self.db.open()

    async def asyncTearDown(self):
        await self.db.close()

    async def test_database_connection(self):
        rows = await self.db.execute("SELECT 1 AS status")
        self.assertEqual(rows[0]["status"], 1)
```

### Docker Compose for Tests

Use the project's `compose.yaml` (run via `just docker`), or create a
minimal test compose file:

```yaml
services:
  postgres-test:
    image: ghcr.io/aweber-imbi/postgres:latest
    ports:
      - "5432:5432"
    environment:
      POSTGRES_PASSWORD: secret
    tmpfs:
      - /var/lib/postgresql/data

  clickhouse-test:
    image: clickhouse/clickhouse-server:latest
    ports:
      - "8123:8123"
    tmpfs:
      - /var/lib/clickhouse
```

Start test databases:

```bash
docker compose -f docker-compose.test.yml up -d
```

Run tests:

```bash
# Run all tests
just test

# Skip integration tests
SKIP_INTEGRATION_TESTS=1 python -m unittest discover tests
```

## Mocking

Mock database clients for isolated testing.

### Mocking the Graph Client

```python
import unittest
from unittest.mock import AsyncMock, MagicMock
from imbi_common import graph, models

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
    @patch('imbi_common.clickhouse.query')
    async def test_query_analytics(self, mock_query):
        mock_query.return_value = [
            {"user_id": "user1", "count": 10},
            {"user_id": "user2", "count": 5}
        ]

        from imbi_common import clickhouse

        results = await clickhouse.query(
            "SELECT user_id, COUNT(*) as count "
            "FROM session_activity GROUP BY user_id"
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["user_id"], "user1")
```

## Running Tests

### Run All Tests

```bash
just test
```

### Run Specific Test File

```bash
just test tests/test_settings.py
```

### Run Specific Test Method

```bash
just test tests/test_settings.py::TestSettings::test_postgres_defaults
```

### Run with Verbose Output

```bash
python -m unittest discover tests -v
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: ghcr.io/aweber-imbi/postgres:latest
        env:
          POSTGRES_PASSWORD: secret
        ports:
          - 5432:5432

      clickhouse:
        image: clickhouse/clickhouse-server:latest
        ports:
          - 8123:8123

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run unit tests
        run: SKIP_INTEGRATION_TESTS=1 python -m unittest discover tests

      - name: Run integration tests
        env:
          POSTGRES_URL: postgresql://postgres:secret@localhost:5432/imbi
          CLICKHOUSE_URL: clickhouse+http://localhost:8123
        run: python -m unittest discover tests
```

## Test Coverage

Track test coverage with `coverage` (via `just test`):

```bash
# Run tests with coverage (requires Docker for integration tests)
just test

# Run specific file without coverage
just test tests/test_settings.py
```

Add to `.coveragerc`:

```ini
[run]
source = src/imbi_common
omit =
    */tests/*
    */test_*.py

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
    if TYPE_CHECKING:
```

## Best Practices

1. **Isolate Tests**: Each test should be independent
2. **Clean Up**: Always clean up test data in `tearDown`/`asyncTearDown`
3. **Use Fixtures**: Create reusable test data with fixtures
4. **Mock External Services**: Don't hit real APIs in unit tests
5. **Test Edge Cases**: Test error conditions and boundary cases
6. **Fast Unit Tests**: Keep unit tests fast by avoiding I/O
7. **Clear Test Names**: Use descriptive test method names
8. **One Assert Per Test**: Focus each test on one behavior
