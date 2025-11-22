"""
Pytest configuration and shared fixtures for Imbi tests.
"""
import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from piccolo.conf.apps import Finder
from piccolo.table import create_db_tables, drop_db_tables

from imbi.api.app import create_app
from imbi.config import Config
from imbi.database import close_database, initialize_database
from imbi.models import Group, Namespace, User

# Set test environment
os.environ["IMBI_ENVIRONMENT"] = "test"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_config() -> Config:
    """
    Create test configuration.

    Uses in-memory or test database to avoid affecting real data.
    """
    return Config(
        debug=True,
        environment="test",
        encryption_key="dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==",  # base64: "test-encryption-key-for-testing"
        http={"host": "127.0.0.1", "port": 8000, "workers": 1, "reload": False},
        postgres={
            "host": os.getenv("TEST_POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("TEST_POSTGRES_PORT", "5432")),
            "database": os.getenv("TEST_POSTGRES_DB", "imbi_test"),
            "user": os.getenv("TEST_POSTGRES_USER", "imbi"),
            "password": os.getenv("TEST_POSTGRES_PASSWORD", "imbi"),
            "min_pool_size": 1,
            "max_pool_size": 5,
            "timeout": 10,
            "log_queries": True,
        },
        session={
            "valkey": {
                "url": os.getenv("TEST_VALKEY_URL", "valkey://localhost:6379/15"),  # Use DB 15 for tests
                "encoding": "utf-8",
                "decode_responses": True,
            },
            "cookie_name": "test_session",
            "duration": 1,  # 1 day
            "secret_key": "dGVzdC1zZWNyZXQta2V5",
        },
        stats={
            "enabled": False,  # Disable stats in tests
            "valkey": {
                "url": os.getenv("TEST_VALKEY_URL", "valkey://localhost:6379/15"),
                "encoding": "utf-8",
                "decode_responses": True,
            },
        },
        ldap={"enabled": False},
        cors={"enabled": True, "allowed_origins": ["*"]},
        opensearch={"enabled": False},
        claude={"enabled": False, "api_key": ""},
        mcp={"enabled": False},
        sentry={"enabled": False},
    )


@pytest_asyncio.fixture(scope="session")
async def database(test_config: Config) -> AsyncGenerator[None, None]:
    """
    Initialize test database and create tables.

    This fixture runs once per test session.
    """
    # Initialize database connection
    await initialize_database(
        host=test_config.postgres.host,
        port=test_config.postgres.port,
        database=test_config.postgres.database,
        user=test_config.postgres.user,
        password=test_config.postgres.password,
        min_pool_size=test_config.postgres.min_pool_size,
        max_pool_size=test_config.postgres.max_pool_size,
        timeout=test_config.postgres.timeout,
        log_queries=test_config.postgres.log_queries,
    )

    # Create all tables
    from imbi.models import GroupMember

    tables = [User, Group, GroupMember, Namespace]  # Add more as we create them
    await create_db_tables(*tables, if_not_exists=True)

    yield

    # Cleanup: Drop tables and close connection
    await drop_db_tables(*tables)
    await close_database()


@pytest_asyncio.fixture
async def clean_database(database) -> AsyncGenerator[None, None]:
    """
    Clean database before each test.

    Truncates all tables to ensure test isolation.
    """
    from imbi.models import GroupMember

    # Truncate all tables (order matters for foreign keys)
    tables = [GroupMember, Namespace, Group, User]
    for table in tables:
        await table.delete(force=True)

    yield

    # Cleanup after test (optional, since next test will truncate anyway)


@pytest_asyncio.fixture
async def app(test_config: Config, database) -> AsyncGenerator:
    """Create FastAPI application for testing."""
    application = create_app(test_config)
    yield application


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """
    Create async HTTP client for testing.

    This client doesn't require a running server.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def test_user(clean_database, test_config: Config) -> dict:
    """
    Create a test user in the database.

    Returns:
        User data dictionary
    """
    from imbi.services.user import User as UserService

    # Hash password properly using the same method as authentication
    user_service = UserService(config=test_config)
    hashed_password = user_service.hash_password("password")

    user = User(
        username="testuser",
        user_type="internal",
        email_address="test@example.com",
        display_name="Test User",
        password=hashed_password,
    )
    await user.save()

    result = await User.select().where(User.username == "testuser").first()
    return result


@pytest_asyncio.fixture
async def admin_user(clean_database, test_config: Config) -> dict:
    """
    Create an admin user in the database.

    Returns:
        Admin user data dictionary
    """
    from imbi.models import GroupMember
    from imbi.services.user import User as UserService

    # Create admin group
    admin_group = Group(
        name="admin",
        permissions=["admin", "reader", "writer"],
        created_by="system",
        last_modified_by="system",
    )
    await admin_group.save()

    # Hash password properly
    user_service = UserService(config=test_config)
    hashed_password = user_service.hash_password("password")

    # Create admin user
    admin = User(
        username="admin",
        user_type="internal",
        email_address="admin@example.com",
        display_name="Admin User",
        password=hashed_password,
    )
    await admin.save()

    # Add user to admin group
    group_member = GroupMember(
        username="admin",
        group="admin",
        added_by="system",
    )
    await group_member.save()

    result = await User.select().where(User.username == "admin").first()
    return result


@pytest_asyncio.fixture
async def authenticated_client(
    client: AsyncClient, test_user: dict
) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an authenticated HTTP client.

    Logs in as the test user and maintains session.
    """
    response = await client.post(
        "/api/login",
        json={"username": "testuser", "password": "password"}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"

    yield client


@pytest_asyncio.fixture
async def admin_client(
    client: AsyncClient, admin_user: dict
) -> AsyncGenerator[AsyncClient, None]:
    """
    Create an authenticated HTTP client with admin privileges.

    Logs in as the admin user and maintains session.
    """
    response = await client.post(
        "/api/login",
        json={"username": "admin", "password": "password"}
    )
    assert response.status_code == 200, f"Admin login failed: {response.text}"

    yield client


@pytest_asyncio.fixture
async def sample_namespace(clean_database, admin_user: dict) -> dict:
    """
    Create a sample namespace for testing.

    Returns:
        Namespace data dictionary
    """
    namespace = Namespace(
        namespace_id=1,
        name="Test Namespace",
        slug="test-namespace",
        icon_class="fas fa-test",
        maintained_by="Test Team",
        created_by=admin_user["username"],
        last_modified_by=admin_user["username"],
    )
    await namespace.save()

    result = (
        await Namespace.select().where(Namespace.namespace_id == 1).first()
    )
    return result


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "integration: Integration tests requiring database")
    config.addinivalue_line("markers", "slow: Slow-running tests")
    config.addinivalue_line("markers", "external: Tests requiring external services")
