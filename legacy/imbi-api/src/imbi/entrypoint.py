import asyncio
import datetime
import getpass
import pathlib
import tomllib
import typing
from importlib import resources

import typer
import uvicorn

from imbi import clickhouse, models, neo4j, settings, version
from imbi.auth import core, seed

main = typer.Typer()


class UvicornParameters(typing.TypedDict):
    factory: bool
    host: str
    log_config: dict[str, typing.Any]
    port: int
    reload: typing.NotRequired[bool]
    reload_dirs: typing.NotRequired[list[str]]
    reload_excludes: typing.NotRequired[list[str]]
    proxy_headers: typing.NotRequired[bool]
    headers: typing.NotRequired[list[tuple[str, str]]]
    date_header: typing.NotRequired[bool]
    server_header: typing.NotRequired[bool]
    ws: typing.Literal[
        'auto', 'none', 'websockets', 'websockets-sansio', 'wsproto'
    ]


@main.command()
def serve(
    *,
    dev: bool = False,
) -> None:
    """Start the Imbi HTTP server"""
    config = settings.ServerConfig()

    log_config_file = resources.files('imbi') / 'log-config.toml'
    log_config = tomllib.loads(log_config_file.read_text())

    params: UvicornParameters = {
        'factory': True,
        'host': config.host,
        'port': config.port,
        'log_config': log_config,
        'proxy_headers': True,
        'headers': [('Server', f'imbi/{version}')],
        'date_header': True,
        'server_header': False,
        'ws': 'none',
    }

    if dev or config.environment == 'development':
        loggers = typing.cast(
            'dict[str, dict[str, object]]',
            log_config.setdefault('loggers', {}),
        )
        loggers.setdefault('imbi', {})
        loggers['imbi']['level'] = 'DEBUG'

        params.update(
            {
                'reload': True,
                'reload_dirs': [str(pathlib.Path.cwd() / 'src' / 'imbi')],
                'reload_excludes': ['**/*.pyc'],
            }
        )

    uvicorn.run('imbi.app:create_app', **params)


@main.command()
def setup() -> None:
    """
    Initialize Imbi instance with authentication system and admin user.

    This command sets up a new Imbi instance by:
    1. Seeding permissions and default roles (admin, developer, readonly)
    2. Creating the initial admin user with interactive prompts

    Run this command once when setting up a new Imbi instance.
    """
    asyncio.run(_setup_async())


async def _setup_async() -> None:
    """Async implementation of setup command."""
    typer.echo('=== Imbi Setup ===\n')

    # Initialize Neo4j connection
    try:
        await neo4j.initialize()
    except Exception as e:
        typer.echo(f'✗ Failed to connect to Neo4j: {e}', err=True)
        raise typer.Exit(code=1) from e

    # Initialize ClickHouse connection
    try:
        await clickhouse.initialize()
    except Exception as e:
        typer.echo(f'✗ Failed to connect to ClickHouse: {e}', err=True)
        await neo4j.aclose()
        raise typer.Exit(code=1) from e

    try:
        # Check if system is already set up
        is_seeded = await seed.check_if_seeded()
        has_admin = await _check_admin_exists()

        if is_seeded and has_admin:
            typer.echo('⚠ System appears to be already set up.')
            if not typer.confirm(
                'Continue anyway? This will create additional data.',
                default=False,
            ):
                typer.echo('Setup cancelled.')
                return

        # Step 1: Seed permissions and roles
        typer.echo('Step 1: Seeding permissions and roles...')
        seed_result = await seed.bootstrap_auth_system()

        if seed_result['permissions'] > 0 or seed_result['roles'] > 0:
            typer.echo(
                f'  ✓ Created {seed_result["permissions"]} permissions '
                f'and {seed_result["roles"]} roles'
            )
        else:
            typer.echo(
                '  ✓ Permissions and roles already exist '
                '(no new entities created)'
            )

        # Step 2: Create admin user
        typer.echo('\nStep 2: Create initial admin user')

        # Prompt for user details
        email = typer.prompt('  Email', default='admin@example.com')
        display_name = typer.prompt('  Display name', default='Administrator')

        # Prompt for password securely (won't echo to terminal)
        password = getpass.getpass('  Password: ')
        if not password:
            typer.echo('✗ Password cannot be empty', err=True)
            raise typer.Exit(code=1) from None

        password_confirm = getpass.getpass('  Confirm password: ')
        if password != password_confirm:
            typer.echo('✗ Passwords do not match', err=True)
            raise typer.Exit(code=1) from None

        # Create admin user
        try:
            admin_user = await _create_admin_user(
                email=email,
                display_name=display_name,
                password=password,
            )
            typer.echo(f'  ✓ Created admin user: {admin_user.email}')
        except Exception as e:
            typer.echo(f'✗ Failed to create admin user: {e}', err=True)
            raise typer.Exit(code=1) from e

        # Step 3: Set up ClickHouse schema
        typer.echo('\nStep 3: Setting up ClickHouse schema...')
        try:
            await clickhouse.setup_schema()
            typer.echo('  ✓ ClickHouse schema created successfully')
        except Exception as e:
            typer.echo(f'✗ Failed to set up ClickHouse schema: {e}', err=True)
            raise typer.Exit(code=1) from e

        # Success message
        typer.echo('\n✓ Setup complete!')
        typer.echo(f'\nYou can now log in with: {email}')

    finally:
        await neo4j.aclose()
        await clickhouse.aclose()


async def _check_admin_exists() -> bool:
    """Check if any admin users exist in the system."""
    query = """
    OPTIONAL MATCH (u:User)
    WHERE u.is_admin = true
    RETURN count(u) AS count
    """

    async with neo4j.run(query) as result:
        records = await result.data()
        if records and records[0].get('count', 0) > 0:
            return True

    return False


async def _create_admin_user(
    email: str,
    display_name: str,
    password: str,
) -> models.User:
    """Create an admin user with the specified credentials.

    Args:
        email: Email address for the admin user
        display_name: Display name for the admin user
        password: Plaintext password (will be hashed)

    Returns:
        Created User model

    Raises:
        Exception: If user creation fails
    """
    # Hash the password
    password_hash = core.hash_password(password)

    # Create user model
    user = models.User(
        email=email,
        display_name=display_name,
        password_hash=password_hash,
        is_active=True,
        is_admin=True,
        is_service_account=False,
        created_at=datetime.datetime.now(datetime.UTC),
    )

    # Create user in Neo4j
    query = """
    MERGE (u:User {email: $email})
    ON CREATE SET
        u.display_name = $display_name,
        u.password_hash = $password_hash,
        u.is_active = $is_active,
        u.is_admin = $is_admin,
        u.is_service_account = $is_service_account,
        u.created_at = datetime($created_at)
    ON MATCH SET
        u.display_name = $display_name,
        u.password_hash = $password_hash,
        u.is_active = $is_active,
        u.is_admin = $is_admin,
        u.is_service_account = $is_service_account
    RETURN u
    """

    async with neo4j.run(
        query=query,
        email=user.email,
        display_name=user.display_name,
        password_hash=user.password_hash,
        is_active=user.is_active,
        is_admin=user.is_admin,
        is_service_account=user.is_service_account,
        created_at=user.created_at.isoformat(),
    ) as result:
        records = await result.data()
        if not records:
            raise RuntimeError('Failed to create user')

    # Assign admin role to user
    role_query = """
    MATCH (u:User {email: $email})
    MATCH (r:Role {slug: 'admin'})
    MERGE (u)-[:HAS_ROLE]->(r)
    """

    async with neo4j.run(query=role_query, email=email) as result:
        await result.consume()

    return user
