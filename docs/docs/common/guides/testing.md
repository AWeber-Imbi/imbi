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
    def test_default_neo4j_url(self):
        config = settings.Neo4j()
        self.assertEqual(str(config.url), "neo4j://localhost:7687")

    def test_credential_extraction(self):
        config = settings.Neo4j(
            url="neo4j://user:pass@host:7687"
        )
        self.assertEqual(config.user, "user")
        self.assertEqual(config.password, "pass")
```

### Async Test Cases

For async functions, use `IsolatedAsyncioTestCase`:

```python
import unittest
from imbi_common import neo4j, models

class TestNeo4jOperations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        """Run before each test"""
        await neo4j.initialize()

    async def asyncTearDown(self):
        """Run after each test"""
        await neo4j.aclose()

    async def test_create_node(self):
        project = models.Project(
            name="Test Project",
            slug="test-project",
            description="Test"
        )
        created = await neo4j.create_node(project)
        self.assertEqual(created.name, "Test Project")

        # Cleanup
        await neo4j.delete_node(created)
```

## Unit Tests

Unit tests should not require external dependencies.

### Testing Settings

```python
import unittest
from imbi_common import settings

class TestSettings(unittest.TestCase):
    def test_neo4j_defaults(self):
        config = settings.Neo4j()
        self.assertEqual(str(config.url), "neo4j://localhost:7687")
        self.assertEqual(config.database, "neo4j")
        self.assertTrue(config.keep_alive)

    def test_clickhouse_defaults(self):
        config = settings.Clickhouse()
        self.assertEqual(str(config.url), "http://localhost:8123")
```

### Testing Models

```python
import unittest
from imbi_common import models

class TestModels(unittest.TestCase):
    def test_project_creation(self):
        project = models.Project(
            name="Test Project",
            slug="test-project",
            description="Test description"
        )
        self.assertEqual(project.name, "Test Project")
        self.assertEqual(project.slug, "test-project")

    def test_slug_generation(self):
        project = models.Project(
            name="My Test Project"
        )
        self.assertEqual(project.slug, "my-test-project")
```

### Testing Auth Functions

```python
import unittest
from imbi_common.auth import core

class TestAuth(unittest.TestCase):
    def test_password_hashing(self):
        password = "secure_password_123"
        hashed = core.hash_password(password)

        # Verify password
        self.assertTrue(core.verify_password(password, hashed))

        # Wrong password should fail
        self.assertFalse(
            core.verify_password("wrong_password", hashed)
        )

    def test_jwt_creation_and_verification(self):
        token = core.create_access_token(
            subject="user@example.com",
            extra_claims={"role": "admin"}
        )

        # Verify token
        payload = core.verify_token(token)
        self.assertEqual(payload["sub"], "user@example.com")
        self.assertEqual(payload["role"], "admin")
```

### Testing Logging

```python
import unittest
from imbi_common import logging

class TestLogging(unittest.TestCase):
    def test_get_log_config(self):
        config = logging.get_log_config()
        self.assertIn("version", config)
        self.assertIn("formatters", config)
        self.assertIn("handlers", config)

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
from imbi_common import neo4j

@unittest.skipIf(
    os.environ.get('SKIP_INTEGRATION_TESTS'),
    "Skipping integration tests (SKIP_INTEGRATION_TESTS set)"
)
class TestNeo4jIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await neo4j.initialize()

    async def asyncTearDown(self):
        await neo4j.aclose()

    async def test_database_connection(self):
        result = await neo4j.execute_read(
            "RETURN 'connected' as status"
        )
        self.assertEqual(result[0]['status'], 'connected')
```

### Docker Compose for Tests

Create `docker-compose.test.yml`:

```yaml
services:
  neo4j-test:
    image: neo4j:5-community
    ports:
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/testpassword
      NEO4J_PLUGINS: '["apoc"]'
    tmpfs:
      - /data

  clickhouse-test:
    image: clickhouse/clickhouse-server:latest
    ports:
      - "8123:8123"
    tmpfs:
      - /var/lib/clickhouse
```

Start test databases:

```bash
docker-compose -f docker-compose.test.yml up -d
```

Run integration tests:

```bash
# Run all tests
python -m unittest discover tests

# Skip integration tests
SKIP_INTEGRATION_TESTS=1 python -m unittest discover tests
```

### Base Test Classes

Create reusable base classes for integration tests:

```python
# tests/__init__.py

import os
import unittest
from imbi_common import neo4j, clickhouse

class Neo4jTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class for tests requiring Neo4j."""

    @classmethod
    def setUpClass(cls):
        if os.environ.get('SKIP_INTEGRATION_TESTS'):
            raise unittest.SkipTest("Integration tests disabled")

    async def asyncSetUp(self):
        await neo4j.initialize()

    async def asyncTearDown(self):
        # Clean up test data
        await neo4j.execute_write("MATCH (n) DETACH DELETE n")
        await neo4j.aclose()

class ClickHouseTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class for tests requiring ClickHouse."""

    @classmethod
    def setUpClass(cls):
        if os.environ.get('SKIP_INTEGRATION_TESTS'):
            raise unittest.SkipTest("Integration tests disabled")

    async def asyncSetUp(self):
        await clickhouse.initialize()
        await clickhouse.setup_schema()
```

Use base classes:

```python
from tests import Neo4jTestCase
from imbi_common import models, neo4j

class TestProjectCRUD(Neo4jTestCase):
    async def test_create_and_fetch_project(self):
        # Create
        project = models.Project(
            name="Integration Test Project",
            slug="integration-test-project",
            description="Test"
        )
        created = await neo4j.create_node(project)

        # Fetch
        fetched = await neo4j.fetch_node(
            models.Project,
            {"slug": "integration-test-project"}
        )

        self.assertEqual(fetched.name, "Integration Test Project")
        self.assertEqual(fetched.slug, created.slug)
```

## Mocking

Mock database clients for isolated testing.

### Mocking Neo4j

```python
import unittest
from unittest.mock import AsyncMock, patch
from imbi_common import models

class TestServiceLogic(unittest.IsolatedAsyncioTestCase):
    @patch('imbi_common.neo4j.fetch_node')
    async def test_get_project(self, mock_fetch):
        # Setup mock
        mock_project = models.Project(
            name="Mocked Project",
            slug="mocked-project",
            description="Test"
        )
        mock_fetch.return_value = mock_project

        # Import after patching
        from imbi_common import neo4j

        # Test
        project = await neo4j.fetch_node(
            models.Project,
            {"slug": "mocked-project"}
        )

        self.assertEqual(project.name, "Mocked Project")
        mock_fetch.assert_called_once()
```

### Mocking ClickHouse

```python
import unittest
from unittest.mock import AsyncMock, patch

class TestAnalytics(unittest.IsolatedAsyncioTestCase):
    @patch('imbi_common.clickhouse.query')
    async def test_query_analytics(self, mock_query):
        # Setup mock
        mock_query.return_value = [
            {"user_id": "user1", "count": 10},
            {"user_id": "user2", "count": 5}
        ]

        # Import after patching
        from imbi_common import clickhouse

        # Test
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
python -m unittest discover tests
```

### Run Specific Test Module

```bash
python -m unittest tests.test_settings
```

### Run Specific Test Class

```bash
python -m unittest tests.test_settings.TestSettings
```

### Run Specific Test Method

```bash
python -m unittest tests.test_settings.TestSettings.test_default_neo4j_url
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
      neo4j:
        image: neo4j:5-community
        env:
          NEO4J_AUTH: neo4j/testpassword
        ports:
          - 7687:7687

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
        run: |
          pip install -e ".[dev]"

      - name: Run unit tests
        run: |
          SKIP_INTEGRATION_TESTS=1 python -m unittest discover tests

      - name: Run integration tests
        env:
          NEO4J_URL: neo4j://neo4j:testpassword@localhost:7687
          CLICKHOUSE_URL: http://localhost:8123
        run: |
          python -m unittest discover tests
```

## Test Coverage

Track test coverage with `coverage`:

```bash
# Install coverage
pip install coverage

# Run tests with coverage
coverage run -m unittest discover tests

# Generate report
coverage report

# Generate HTML report
coverage html
open htmlcov/index.html
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
4. **Mock External Services**: Don't hit real APIs in tests
5. **Test Edge Cases**: Test error conditions and boundary cases
6. **Fast Unit Tests**: Keep unit tests fast by avoiding I/O
7. **Clear Test Names**: Use descriptive test method names
8. **One Assert Per Test**: Focus each test on one behavior
