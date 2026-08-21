import asyncio
import datetime
import getpass
import typing

import typer

from imbi.api import models
from imbi.api.auth import internal_services, seed
from imbi.api.auth import password as password_auth
from imbi.api.graph_sql import set_clause
from imbi.common import clickhouse, graph, server

main = typer.Typer(no_args_is_help=True)
main.command('serve')(server.bind_entrypoint('imbi.api.app:create_app'))


@main.command('setup-clickhouse')
def setup_clickhouse() -> None:
    """Apply the ClickHouse schema without running the full setup.

    Executes the enabled DDL from the packaged ``schemata.toml`` — the
    same work as the last step of ``setup`` — so a deployment that adds tables
    or materialized views can roll them out without re-seeding auth or
    re-prompting for an admin user. Idempotent.
    """
    asyncio.run(_setup_clickhouse_async())


async def _setup_clickhouse_async() -> None:
    """Async body of ``setup-clickhouse``."""
    try:
        connected = await clickhouse.initialize()
    except Exception as e:
        typer.echo(f'✗ Failed to connect to ClickHouse: {e}', err=True)
        raise typer.Exit(code=1) from e
    if not connected:
        typer.echo(
            '✗ Failed to connect to ClickHouse: connection attempts exhausted',
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        await _apply_clickhouse_schema()
    finally:
        await clickhouse.aclose()


async def _apply_clickhouse_schema() -> None:
    """Execute the packaged ClickHouse DDL, reporting progress."""
    try:
        await clickhouse.setup_schema()
        typer.echo('  ✓ ClickHouse schema created successfully')
    except Exception as e:
        typer.echo(f'✗ Failed to set up ClickHouse schema: {e}', err=True)
        raise typer.Exit(code=1) from e


@main.command('setup-postgres')
def setup_postgres() -> None:
    """Apply the PostgreSQL graph schema without running the full setup.

    Runs the graph initializer from the packaged ``schemata.toml`` — the
    same work the API performs at startup — so a deployment that adds
    vertex labels, indexes, or functions can roll them out without
    starting the server or re-seeding auth. Idempotent: existing labels
    are left untouched and only missing ones are created.
    """
    asyncio.run(_setup_postgres_async())


async def _setup_postgres_async() -> None:
    """Async body of ``setup-postgres``."""
    try:
        await graph.initialize()
    except Exception as e:
        typer.echo(
            f'✗ Failed to set up PostgreSQL graph schema: {e}', err=True
        )
        raise typer.Exit(code=1) from e
    typer.echo('  ✓ PostgreSQL graph schema is up to date')


@main.command('setup-permissions')
def setup_permissions() -> None:
    """Seed permissions and default roles without running the full setup.

    Prunes retired permissions, then re-seeds the standard permissions
    and default roles, refreshing each role's GRANTS edges. Use this to
    roll out permissions added by a release without re-seeding an
    organization or touching the admin user. Idempotent.
    """
    asyncio.run(_setup_permissions_async())


async def _setup_permissions_async() -> None:
    """Async body of ``setup-permissions``."""
    db = graph.Graph()
    try:
        await db.open()
    except Exception as e:
        typer.echo(f'✗ Failed to connect to PostgreSQL: {e}', err=True)
        raise typer.Exit(code=1) from e

    try:
        result = await seed.seed_permissions_and_roles(db)
    except Exception as e:
        typer.echo(f'✗ Failed to seed permissions and roles: {e}', err=True)
        raise typer.Exit(code=1) from e
    finally:
        await db.close()

    if result['retired']:
        typer.echo(f'  ✓ Removed {result["retired"]} retired permission(s)')
    if result['permissions'] or result['roles']:
        typer.echo(
            f'  ✓ Created {result["permissions"]} permission(s) '
            f'and {result["roles"]} role(s)'
        )
    else:
        typer.echo(
            '  ✓ Permissions and roles already exist (no new entities created)'
        )
    typer.echo('\n✓ Permissions and roles are up to date')


@main.command('setup-service-accounts')
def setup_service_accounts(
    organization: typing.Annotated[
        str | None,
        typer.Option(
            help=(
                'Organization the service accounts join. Defaults to the '
                'only organization when there is exactly one.'
            ),
        ),
    ] = None,
) -> None:
    """Seed the service accounts imbi-scheduler and imbi-gateway use.

    The credential-seeding half of ``setup``, for an install that was
    set up before it existed. Requires ``setup-permissions`` to have run
    first: each account is granted a seeded role by name. Idempotent —
    an existing credential is never rotated.
    """
    asyncio.run(_setup_service_accounts_async(organization))


async def _setup_service_accounts_async(org_slug: str | None) -> None:
    """Async body of ``setup-service-accounts``."""
    db = graph.Graph()
    try:
        await db.open()
    except Exception as e:
        typer.echo(f'✗ Failed to connect to PostgreSQL: {e}', err=True)
        raise typer.Exit(code=1) from e

    try:
        if org_slug is None:
            org_slug = await _sole_organization_slug(db)
        results = await internal_services.seed_internal_services(db, org_slug)
    except internal_services.SeedError as e:
        typer.echo(f'✗ {e}', err=True)
        raise typer.Exit(code=1) from e
    except typer.Exit:
        # `_sole_organization_slug` has already reported the problem;
        # `typer.Exit` is a `RuntimeError`, so without this the generic
        # handler below would bury that message under its own.
        raise
    except Exception as e:
        typer.echo(f'✗ Failed to seed service accounts: {e}', err=True)
        raise typer.Exit(code=1) from e
    finally:
        await db.close()

    _report_service_accounts(results)


async def _sole_organization_slug(db: graph.Graph) -> str:
    """Return the only organization's slug.

    Raises ``typer.Exit`` when there is not exactly one: guessing which
    organization owns the internal service accounts would put them in a
    tenant whose projects they were never meant to touch.
    """
    records = await db.execute(
        'MATCH (o:Organization) RETURN o.slug AS slug ORDER BY o.slug',
        columns=['slug'],
    )
    slugs = [graph.parse_agtype(record['slug']) for record in records]
    if len(slugs) == 1:
        return str(slugs[0])
    if not slugs:
        typer.echo(
            '✗ No organization exists yet. Run `imbi-api setup` first.',
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo(
        '✗ Multiple organizations exist; pass --organization with one of: '
        + ', '.join(str(slug) for slug in slugs),
        err=True,
    )
    raise typer.Exit(code=1)


def _report_service_accounts(
    results: list[internal_services.SeededService],
) -> None:
    """Print what was seeded, emitting generated credentials once.

    A generated secret is unrecoverable after this, so it is printed as
    an assignment a deployment can paste straight into its environment
    rather than described in prose.
    """
    emit: dict[str, str] = {}
    for result in results:
        account = 'created' if result.account_created else 'already exists'
        if result.outcome == 'supplied':
            detail = f'credential matches ${result.service.secret_var}'
        elif result.outcome == 'unchanged':
            detail = 'existing credential left in place'
        else:
            detail = 'credential generated (shown once below)'
            emit.update(result.env)
        typer.echo(f'  ✓ {result.service.slug}: {account}, {detail}')
    if not emit:
        return
    typer.echo(
        '\n  Set these before starting the services — the secrets cannot '
        'be read back:'
    )
    for name, value in emit.items():
        typer.echo(f'    {name}={value}')


@main.command()
def setup() -> None:
    """
    Initialize Imbi instance with authentication system and admin user.

    This command sets up a new Imbi instance by:
    1. Seeding permissions and default roles (admin, developer, readonly)
    2. Creating the initial admin user with interactive prompts
    3. Seeding the service accounts imbi-scheduler and imbi-gateway
       authenticate to imbi-api as
    4. Applying the ClickHouse schema

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
        connected = await clickhouse.initialize()
    except Exception as e:
        typer.echo(f'✗ Failed to connect to ClickHouse: {e}', err=True)
        await db.close()
        raise typer.Exit(code=1) from e
    if not connected:
        typer.echo(
            '✗ Failed to connect to ClickHouse: connection attempts exhausted',
            err=True,
        )
        await db.close()
        raise typer.Exit(code=1)

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
            raise typer.Exit(code=1)

        password_confirm = getpass.getpass('  Confirm password: ')
        if password != password_confirm:
            typer.echo('✗ Passwords do not match', err=True)
            raise typer.Exit(code=1)

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

        # Step 3: Seed the service accounts Imbi's own services use
        typer.echo('\nStep 3: Seeding internal service accounts...')
        try:
            seeded = await internal_services.seed_internal_services(
                db, org_slug
            )
        except internal_services.SeedError as e:
            typer.echo(f'✗ {e}', err=True)
            raise typer.Exit(code=1) from e
        except Exception as e:
            typer.echo(f'✗ Failed to seed service accounts: {e}', err=True)
            raise typer.Exit(code=1) from e
        _report_service_accounts(seeded)

        # Step 4: Set up ClickHouse schema
        typer.echo('\nStep 4: Setting up ClickHouse schema...')
        await _apply_clickhouse_schema()

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

    # Create user in graph (AGE has no ON CREATE/MATCH SET).
    # L12: use ``set_clause`` so the property-name → placeholder
    # plumbing is centralized + identifier-validated rather than
    # hand-typed.
    fields: dict[str, typing.Any] = {
        'display_name': user.display_name,
        'password_hash': user.password_hash,
        'is_active': user.is_active,
        'is_admin': user.is_admin,
        'is_service_account': user.is_service_account,
        'created_at': user.created_at.isoformat(),
    }
    query: typing.LiteralString = (
        'MERGE (n:User {{email: {email}}}) '
        + set_clause('n', fields)
        + ' RETURN n'
    )
    records = await db.execute(query, {'email': user.email, **fields})
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
    membership_records = await db.execute(
        membership_query,
        {'email': email, 'org_slug': org_slug},
        columns=['m'],
    )
    if not membership_records:
        # Empty result = the User/Organization MATCH didn't bind, so the
        # MERGE never fired. Fail fast rather than leaving an admin with
        # no organization membership.
        raise RuntimeError(
            f'Failed to grant {email!r} admin membership in '
            f'organization {org_slug!r}: organization not found'
        )

    return user
