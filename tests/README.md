# Imbi Testing Guide

This directory contains the test suite for Imbi 2.0 (FastAPI migration).

## Test Infrastructure

### Framework
- **pytest**: Modern Python testing framework with async support
- **pytest-asyncio**: Async test support
- **httpx**: Async HTTP client for API testing
- **Piccolo**: ORM for database operations in tests

### Test Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── test_health.py           # Health check endpoint tests
├── test_namespaces.py       # Namespace CRUD tests
├── test_auth.py             # Authentication/authorization tests
└── README.md                # This file
```

## Setup

### 1. Install Test Dependencies

```bash
# Install Imbi with test dependencies
pip install -e ".[test]"
```

### 2. Configure Test Database

Tests use a separate database to avoid affecting production/development data.

**Option A: Use Docker Compose** (Recommended)

```bash
# Start test infrastructure
docker-compose -f docker-compose.test.yml up -d

# This starts:
# - PostgreSQL on port 5433 (database: imbi_test)
# - Valkey on port 6380 (DB 15 for tests)
```

**Option B: Use Existing Services**

Set environment variables to point to test instances:

```bash
export TEST_POSTGRES_HOST=localhost
export TEST_POSTGRES_PORT=5432
export TEST_POSTGRES_DB=imbi_test
export TEST_POSTGRES_USER=imbi
export TEST_POSTGRES_PASSWORD=imbi
export TEST_VALKEY_URL=valkey://localhost:6379/15
```

### 3. Create Test Database

```bash
# Create the test database
createdb -U postgres imbi_test

# Or via psql
psql -U postgres -c "CREATE DATABASE imbi_test;"
```

## Running Tests

### Run All Tests

```bash
pytest
```

### Run Specific Test File

```bash
pytest tests/test_namespaces.py
```

### Run Specific Test Class

```bash
pytest tests/test_namespaces.py::TestListNamespaces
```

### Run Specific Test

```bash
pytest tests/test_namespaces.py::TestListNamespaces::test_list_empty
```

### Run with Coverage

```bash
# Generate coverage report
pytest --cov=imbi --cov-report=html

# View report
open htmlcov/index.html
```

### Run with Verbose Output

```bash
pytest -v
```

### Run with Output (print statements)

```bash
pytest -s
```

### Run Only Integration Tests

```bash
pytest -m integration
```

### Skip Slow Tests

```bash
pytest -m "not slow"
```

## Test Fixtures

### Database Fixtures

- `database`: Session-scoped fixture that creates/drops tables
- `clean_database`: Function-scoped fixture that truncates tables before each test
- `test_user`: Creates a regular test user
- `admin_user`: Creates an admin user with permissions
- `sample_namespace`: Creates a sample namespace for testing

### Client Fixtures

- `app`: FastAPI application instance
- `client`: Async HTTP client (unauthenticated)
- `authenticated_client`: HTTP client logged in as test user
- `admin_client`: HTTP client logged in as admin user

### Configuration Fixture

- `test_config`: Test configuration with test database settings

## Writing Tests

### Basic Test Example

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_something(client: AsyncClient):
    """Test description."""
    response = await client.get("/api/something")

    assert response.status_code == 200
    assert response.json()["key"] == "value"
```

### Integration Test Example

```python
import pytest
from httpx import AsyncClient
from imbi.models import Namespace


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_namespace(admin_client: AsyncClient, clean_database):
    """Test creating a namespace via API."""
    payload = {
        "namespace_id": 1,
        "name": "Test",
        "slug": "test",
    }

    response = await admin_client.post("/api/namespaces", json=payload)

    assert response.status_code == 201

    # Verify in database
    ns = await Namespace.select().where(Namespace.namespace_id == 1).first()
    assert ns is not None
    assert ns["name"] == "Test"
```

### Test with Custom Fixture

```python
import pytest
from httpx import AsyncClient
from imbi.models import Project


@pytest_asyncio.fixture
async def sample_project(clean_database, admin_user):
    """Create a sample project."""
    project = Project(
        name="Test Project",
        namespace_id=1,
        created_by=admin_user["username"],
        last_modified_by=admin_user["username"],
    )
    await project.save()
    return await Project.select().where(Project.name == "Test Project").first()


@pytest.mark.asyncio
async def test_with_project(client: AsyncClient, sample_project):
    """Test that uses the custom fixture."""
    response = await client.get(f"/api/projects/{sample_project['id']}")
    assert response.status_code == 200
```

## Test Categories

### Unit Tests
- Test individual functions/classes in isolation
- Mock external dependencies
- Fast execution
- No database required

### Integration Tests
- Test API endpoints end-to-end
- Use real database (test instance)
- Marked with `@pytest.mark.integration`
- Test complete request/response cycle

### Slow Tests
- Tests that take >1 second
- Marked with `@pytest.mark.slow`
- Can be skipped: `pytest -m "not slow"`

### External Tests
- Tests requiring external services (LDAP, OAuth, etc.)
- Marked with `@pytest.mark.external`
- Can be skipped: `pytest -m "not external"`

## Continuous Integration

Tests are automatically run on:
- Pull requests
- Pushes to main branch
- Pre-release tags

CI Configuration: `.github/workflows/test.yml`

## Coverage Goals

- **Overall**: >85%
- **API Endpoints**: >90%
- **Business Logic**: >85%
- **Models**: >80%

Check coverage:
```bash
pytest --cov=imbi --cov-report=term-missing
```

## Debugging Tests

### Run Single Test with Print Output

```bash
pytest -s tests/test_namespaces.py::TestListNamespaces::test_list_empty
```

### Run with PDB on Failure

```bash
pytest --pdb
```

### Run with Warnings

```bash
pytest -W default
```

### See All Test Output

```bash
pytest -ra
```

## Common Issues

### Issue: Database Connection Failed

**Solution**: Ensure PostgreSQL is running and test database exists.

```bash
psql -U postgres -c "CREATE DATABASE imbi_test;"
```

### Issue: Valkey Connection Failed

**Solution**: Ensure Valkey/Redis is running.

```bash
# Check if Valkey is running
redis-cli -h localhost -p 6379 ping
```

### Issue: Import Errors

**Solution**: Install package in editable mode.

```bash
pip install -e ".[test]"
```

### Issue: Async Tests Not Running

**Solution**: Ensure pytest-asyncio is installed.

```bash
pip install pytest-asyncio
```

## Best Practices

1. **Test Isolation**: Each test should be independent
2. **Use Fixtures**: Share setup code via fixtures
3. **Descriptive Names**: Test names should describe what they test
4. **One Assert Per Test**: Focus each test on one behavior (when possible)
5. **Test Edge Cases**: Test boundary conditions and error cases
6. **Clean Up**: Use `clean_database` fixture to ensure test isolation
7. **Mark Tests**: Use markers for integration, slow, external tests
8. **Document**: Add docstrings to explain complex test scenarios

## Future Improvements

- [ ] Add performance/benchmark tests
- [ ] Add load testing suite
- [ ] Add mutation testing
- [ ] Add property-based testing (Hypothesis)
- [ ] Add API contract testing
- [ ] Add E2E tests with UI automation

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [HTTPX documentation](https://www.python-httpx.org/)
- [Piccolo testing guide](https://piccolo-orm.readthedocs.io/en/latest/piccolo/testing/index.html)
