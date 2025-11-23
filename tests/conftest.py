"""
Pytest configuration and shared fixtures for Imbi tests.
"""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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
            "port": int(os.getenv("TEST_POSTGRES_PORT", "5433")),  # Docker test port
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
                "url": os.getenv(
                    "TEST_VALKEY_URL", "valkey://localhost:6380/15"
                ),  # Docker test port, DB 15
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
                "url": os.getenv("TEST_VALKEY_URL", "valkey://localhost:6380/15"),
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
        _query_timeout=test_config.postgres.timeout,
        log_queries=test_config.postgres.log_queries,
    )

    # Create all tables
    # Get the database engine
    from imbi.database import get_db
    from imbi.models import (
        Environment,
        FactType,
        GroupMember,
        OperationsLog,
        Project,
        ProjectDependency,
        ProjectFact,
        ProjectLink,
        ProjectLinkType,
        ProjectNote,
        ProjectType,
        ProjectURL,
    )

    db_engine = get_db()

    tables = [
        # User tables
        User,
        Group,
        GroupMember,
        # Admin tables
        Namespace,
        ProjectType,
        Environment,
        # Project tables
        Project,
        ProjectDependency,
        ProjectLinkType,
        ProjectLink,
        ProjectURL,
        FactType,
        ProjectFact,
        ProjectNote,
        # Operations
        OperationsLog,
    ]

    # Set the DB engine on all tables
    for table in tables:
        table._meta.db = db_engine

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
    from imbi.models import (
        Environment,
        FactType,
        GroupMember,
        OperationsLog,
        Project,
        ProjectDependency,
        ProjectFact,
        ProjectLink,
        ProjectLinkType,
        ProjectNote,
        ProjectType,
        ProjectURL,
    )

    # Truncate all tables (order matters for foreign keys - child tables first)
    tables = [
        # Project child tables first
        OperationsLog,
        ProjectNote,
        ProjectFact,
        ProjectURL,
        ProjectLink,
        ProjectDependency,
        # Then parent tables
        Project,
        # Admin child tables
        GroupMember,
        # Admin parent tables
        ProjectLinkType,
        FactType,
        ProjectType,
        Environment,
        Namespace,
        Group,
        User,
    ]
    for table in tables:
        await table.delete(force=True)

    yield

    # Cleanup after test (optional, since next test will truncate anyway)


@pytest_asyncio.fixture
async def app(test_config: Config, database) -> AsyncGenerator:
    """Create FastAPI application for testing."""
    from redis import asyncio as aioredis

    application = create_app(test_config)

    # Manually initialize Valkey connections (lifespan doesn't run in tests)
    # Note: redis-py requires redis:// scheme, not valkey://
    session_url = test_config.session.valkey.url.replace("valkey://", "redis://")
    stats_url = test_config.stats.valkey.url.replace("valkey://", "redis://")

    application.state.session_valkey = await aioredis.from_url(
        session_url,
        encoding=test_config.session.valkey.encoding,
        decode_responses=test_config.session.valkey.decode_responses,
    )
    application.state.stats_valkey = await aioredis.from_url(
        stats_url,
        encoding=test_config.stats.valkey.encoding,
        decode_responses=test_config.stats.valkey.decode_responses,
    )
    application.state.ready = True

    yield application

    # Cleanup
    await application.state.session_valkey.aclose()
    await application.state.stats_valkey.aclose()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """
    Create async HTTP client for testing.

    This client doesn't require a running server.
    Configures cookie jar to persist cookies across requests.
    """
    import httpx

    transport = ASGITransport(app=app)
    # Create client with explicit cookie jar to maintain cookies
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies=httpx.Cookies(),  # Explicit cookie jar
    ) as ac:
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
        "/api/login", json={"username": "testuser", "password": "password"}
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
        "/api/login", json={"username": "admin", "password": "password"}
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

    result = await Namespace.select().where(Namespace.namespace_id == 1).first()
    return result


@pytest_asyncio.fixture
async def sample_project_type(clean_database, admin_user: dict) -> dict:
    """
    Create a sample project type for testing.

    Returns:
        Project type data dictionary
    """
    from imbi.models import ProjectType

    project_type = ProjectType(
        name="HTTP API",
        slug="http-api",
        plural_name="HTTP APIs",
        icon_class="fas fa-server",
        environment_urls=True,
        created_by=admin_user["username"],
        last_modified_by=admin_user["username"],
    )
    await project_type.save()

    return await ProjectType.select().where(ProjectType.name == "HTTP API").first()


@pytest_asyncio.fixture
async def sample_project(
    clean_database, admin_user: dict, sample_namespace: dict, sample_project_type: dict
) -> dict:
    """
    Create a sample project for testing.

    Returns:
        Project data dictionary
    """
    from imbi.models import Project

    project = Project(
        namespace_id=sample_namespace["id"],
        project_type_id=sample_project_type["id"],
        name="Test Project",
        slug="test-project",
        description="A test project",
        created_by=admin_user["username"],
        last_modified_by=admin_user["username"],
    )
    await project.save()

    return await Project.select().where(Project.name == "Test Project").first()


@pytest_asyncio.fixture
async def second_project(
    clean_database, admin_user: dict, sample_namespace: dict, sample_project_type: dict
) -> dict:
    """
    Create a second project for dependency testing.

    Returns:
        Project data dictionary
    """
    from imbi.models import Project

    project = Project(
        namespace_id=sample_namespace["id"],
        project_type_id=sample_project_type["id"],
        name="Database API",
        slug="database-api",
        description="Database service",
        created_by=admin_user["username"],
        last_modified_by=admin_user["username"],
    )
    await project.save()

    return await Project.select().where(Project.name == "Database API").first()


@pytest_asyncio.fixture
async def sample_link_type(clean_database, admin_user: dict) -> dict:
    """
    Create a sample project link type for testing.

    Returns:
        Link type data dictionary
    """
    from imbi.models import ProjectLinkType

    link_type = ProjectLinkType(
        link_type="GitHub",
        icon_class="fab fa-github",
        created_by=admin_user["username"],
        last_modified_by=admin_user["username"],
    )
    await link_type.save()

    return (
        await ProjectLinkType.select()
        .where(ProjectLinkType.link_type == "GitHub")
        .first()
    )


@pytest_asyncio.fixture
async def sample_fact_type(clean_database, admin_user: dict) -> dict:
    """
    Create a sample fact type for testing.

    Returns:
        Fact type data dictionary
    """
    from imbi.models import FactType

    fact_type = FactType(
        name="Language",
        fact_type="string",
        data_type="text",
        description="Programming language",
        weight=10,
        created_by=admin_user["username"],
        last_modified_by=admin_user["username"],
    )
    await fact_type.save()

    return await FactType.select().where(FactType.name == "Language").first()


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "integration: Integration tests requiring database"
    )
    config.addinivalue_line("markers", "slow: Slow-running tests")
    config.addinivalue_line("markers", "external: Tests requiring external services")
