import asyncio
import datetime
import getpass

import typer
from imbi_common import clickhouse, graph, server

from imbi_api import models
from imbi_api.auth import password as password_auth
from imbi_api.auth import seed

main = typer.Typer(no_args_is_help=True)
main.command('serve')(server.bind_entrypoint('imbi_api.app:create_app'))


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

    # Initialize Graph connection
    db = graph.Graph()
    try:
        await db.open()
    except Exception as e:
        typer.echo(f'✗ Failed to connect to PostgreSQL: {e}', err=True)
        raise typer.Exit(code=1) from e

    # Initialize ClickHouse connection
    try:
        await clickhouse.initialize()
    except Exception as e:
        typer.echo(f'✗ Failed to connect to ClickHouse: {e}', err=True)
        await db.close()
        raise typer.Exit(code=1) from e

    try:
        # Check if system is already set up
        is_seeded = await seed.check_if_seeded(db)
        has_admin = await _check_admin_exists(db)

        if is_seeded and has_admin:
            typer.echo('⚠ System appears to be already set up.')
            if not typer.confirm(
                'Continue anyway? This will create additional data.',
                default=False,
            ):
                typer.echo('Setup cancelled.')
                return

        # Step 1: Seed organization, permissions, and roles
        typer.echo('Step 1: Seeding organization, permissions, and roles...')
        org_name = typer.prompt(
            '  Organization name',
            default='AWeber',
        )
        org_slug = typer.prompt(
            '  Organization slug',
            default='aweber',
        )
        seed_result = await seed.bootstrap_auth_system(
            db,
            org_slug=org_slug,
            org_name=org_name,
        )

        if seed_result['organization']:
            typer.echo(
                f'  ✓ Created organization: {org_name} ({org_slug})',
            )
        else:
            typer.echo(
                f'  ✓ Organization already exists: {org_slug}',
            )

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
                db,
                email=email,
                display_name=display_name,
                password=password,
                org_slug=org_slug,
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
            typer.echo(
                f'✗ Failed to set up ClickHouse schema: {e}',
                err=True,
            )
            raise typer.Exit(code=1) from e

        # Success message
        typer.echo('\n✓ Setup complete!')
        typer.echo(f'\nYou can now log in with: {email}')

    finally:
        await db.close()
        await clickhouse.aclose()


async def _check_admin_exists(db: graph.Graph) -> bool:
    """Check if any admin users exist in the system."""
    query = (
        'OPTIONAL MATCH (n:User) '
        'WHERE n.is_admin = true '
        'RETURN count(n) AS cnt'
    )
    records = await db.execute(query, columns=['cnt'])
    if records:
        count = graph.parse_agtype(records[0]['cnt'])
        if count and count > 0:
            return True
    return False


async def _create_admin_user(
    db: graph.Graph,
    email: str,
    display_name: str,
    password: str,
    org_slug: str = 'default',
) -> models.User:
    """Create an admin user with the specified credentials."""
    password_hash = password_auth.hash_password(password)

    user = models.User(
        email=email,
        display_name=display_name,
        password_hash=password_hash,
        is_active=True,
        is_admin=True,
        is_service_account=False,
        created_at=datetime.datetime.now(datetime.UTC),
    )

    # Create user in graph (AGE has no ON CREATE/MATCH SET)
    query = (
        'MERGE (n:User {{email: {email}}}) '
        'SET n.display_name = {display_name}, '
        'n.password_hash = {password_hash}, '
        'n.is_active = {is_active}, '
        'n.is_admin = {is_admin}, '
        'n.is_service_account = {is_service_account}, '
        'n.created_at = {created_at} '
        'RETURN n'
    )
    records = await db.execute(
        query,
        {
            'email': user.email,
            'display_name': user.display_name,
            'password_hash': user.password_hash,
            'is_active': user.is_active,
            'is_admin': user.is_admin,
            'is_service_account': user.is_service_account,
            'created_at': user.created_at.isoformat(),
        },
    )
    if not records:
        raise RuntimeError('Failed to create user')

    # Add user to organization with admin role
    membership_query = (
        'MATCH (u:User {{email: {email}}}), '
        '(o:Organization {{slug: {org_slug}}}) '
        'MERGE (u)-[m:MEMBER_OF]->(o) '
        "SET m.role = 'admin' "
        'RETURN m'
    )
    await db.execute(
        membership_query,
        {'email': email, 'org_slug': org_slug},
        columns=['m'],
    )

    return user
