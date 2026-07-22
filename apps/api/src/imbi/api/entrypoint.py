import asyncio
import datetime
import getpass
import typing

import nanoid
import typer
from imbi_common import clickhouse, graph, server

from imbi_api import models
from imbi_api.auth import password as password_auth
from imbi_api.auth import seed
from imbi_api.graph_sql import set_clause

main = typer.Typer(no_args_is_help=True)
main.command('serve')(server.bind_entrypoint('imbi_api.app:create_app'))


@main.command('backfill-node-ids')
def backfill_node_ids() -> None:
    """Backfill ``id`` on graph nodes that were created without one.

    Idempotent: only assigns ``id`` where it is currently NULL. Run once
    against staging/production after deploying the create-path fix from
    issue #291. Safe to re-run.
    """
    asyncio.run(_backfill_node_ids_async())


async def _backfill_node_ids_async() -> None:
    db = graph.Graph()
    try:
        await db.open()
    except Exception as e:
        typer.echo(f'✗ Failed to connect to PostgreSQL: {e}', err=True)
        raise typer.Exit(code=1) from e

    try:
        integration_count = await _backfill_integration_ids(db)
        typer.echo(
            f'  ✓ Integration: assigned id to {integration_count} node(s)'
        )
    finally:
        await db.close()


async def _backfill_integration_ids(db: graph.Graph) -> int:
    """Assign a fresh nanoid to every ``Integration`` missing one."""
    query = (
        'MATCH (s:Integration)-[:BELONGS_TO]->(o:Organization)'
        ' WHERE s.id IS NULL'
        ' RETURN o.slug AS org_slug, s.slug AS slug'
    )
    records = await db.execute(query, {}, ['org_slug', 'slug'])
    count = 0
    for record in records:
        org_slug = graph.parse_agtype(record['org_slug'])
        slug = graph.parse_agtype(record['slug'])
        update_query = (
            'MATCH (s:Integration {{slug: {slug}}})'
            ' -[:BELONGS_TO]->(o:Organization {{slug: {org_slug}}})'
            ' WHERE s.id IS NULL'
            ' SET s.id = {new_id}'
            ' RETURN s.id AS id'
        )
        updated = await db.execute(
            update_query,
            {
                'slug': slug,
                'org_slug': org_slug,
                'new_id': nanoid.generate(),
            },
            ['id'],
        )
        if updated:
            count += 1
    return count


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


@main.command(name='migrate-oauth-identity')
def migrate_oauth_identity() -> None:
    """Backfill ``OAuthIdentity.provider_slug`` from the parent slug.

    One-shot, idempotent migration introduced with AWeber-Imbi/imbi-api#255.
    OAuth identities are now keyed on
    ``(provider_slug, provider_user_id)`` instead of
    ``(provider_type, provider_user_id)``. This walks every
    ``OAuthIdentity`` node that still carries the legacy ``provider``
    field and rewrites it to ``provider_slug`` by joining on the
    ``ServiceApplication`` whose ``oauth_app_type`` matches the legacy
    value.

    Safe to re-run: rows already carrying ``provider_slug`` are left
    untouched. The legacy unique index on ``(provider, provider_user_id)``
    is dropped after the rewrite.
    """
    asyncio.run(_migrate_oauth_identity_async())


async def _migrate_oauth_identity_async() -> None:
    """Async body of ``migrate-oauth-identity``."""
    db = graph.Graph()
    try:
        await db.open()
    except Exception as e:
        typer.echo(f'✗ Failed to connect to PostgreSQL: {e}', err=True)
        raise typer.Exit(code=1) from e

    try:
        legacy_query = (
            'MATCH (oi:OAuthIdentity) '
            'WHERE oi.provider IS NOT NULL AND oi.provider_slug IS NULL '
            'RETURN oi.provider AS provider, '
            'oi.provider_user_id AS provider_user_id'
        )
        legacy_records = await db.execute(
            legacy_query, columns=['provider', 'provider_user_id']
        )
        if not legacy_records:
            typer.echo('No legacy OAuthIdentity rows found — nothing to do.')
        else:
            typer.echo(
                f'Found {len(legacy_records)} legacy OAuthIdentity row(s)'
            )
            migrated, skipped = await _backfill_provider_slugs(
                db, legacy_records
            )
            typer.echo(f'Migrated {migrated} row(s); skipped {skipped} row(s)')
            if skipped:
                typer.echo(
                    'Skipped rows were left untouched. Re-run after '
                    'configuring the missing ServiceApplications. The legacy '
                    '(provider, provider_user_id) index has been preserved '
                    'so existing OAuth logins keep working until the '
                    'migration completes cleanly.',
                    err=True,
                )
                raise typer.Exit(code=1)

        # Drop the legacy unique index. ``IF EXISTS`` keeps re-runs idempotent
        # once the new ``(provider_slug, provider_user_id)`` index has
        # replaced it via the next initializer pass. Only reached when every
        # legacy row migrated successfully (or there were none to begin with).
        await db.execute(
            'DROP INDEX IF EXISTS '
            'imbi.oauthidentity_provider_provider_user_id_unique_idx'
        )
        typer.echo('✓ Migration complete')
    finally:
        await db.close()


async def _backfill_provider_slugs(
    db: graph.Graph,
    legacy_records: list[dict[str, typing.Any]],
) -> tuple[int, int]:
    """Rewrite ``OAuthIdentity.provider`` to ``provider_slug``.

    Returns ``(migrated, skipped)`` counts.
    """
    migrated = 0
    skipped = 0
    for record in legacy_records:
        legacy_provider = graph.parse_agtype(record['provider'])
        provider_user_id = graph.parse_agtype(record['provider_user_id'])
        slug_records = await db.execute(
            'MATCH (a:ServiceApplication) '
            'WHERE a.oauth_app_type = {oauth_app_type} '
            "AND a.usage IN ['login', 'both'] "
            'RETURN a.slug AS slug',
            {'oauth_app_type': legacy_provider},
            ['slug'],
        )
        if not slug_records:
            typer.echo(
                f'  ! No login ServiceApplication for oauth_app_type='
                f'{legacy_provider!r}; '
                f'provider_user_id={provider_user_id!r} left untouched',
                err=True,
            )
            skipped += 1
            continue
        if len(slug_records) > 1:
            typer.echo(
                f'  ! Multiple login ServiceApplications for oauth_app_type='
                f'{legacy_provider!r}; '
                f'provider_user_id={provider_user_id!r} cannot be migrated '
                f'unambiguously',
                err=True,
            )
            skipped += 1
            continue
        new_slug = graph.parse_agtype(slug_records[0]['slug'])
        await db.execute(
            'MATCH (oi:OAuthIdentity {{provider: {legacy_provider}, '
            'provider_user_id: {provider_user_id}}}) '
            'SET oi.provider_slug = {new_slug} '
            'REMOVE oi.provider',
            {
                'legacy_provider': legacy_provider,
                'provider_user_id': provider_user_id,
                'new_slug': new_slug,
            },
        )
        typer.echo(
            f'  ✓ provider_user_id={provider_user_id!r}: '
            f'{legacy_provider!r} → {new_slug!r}'
        )
        migrated += 1
    return migrated, skipped


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
