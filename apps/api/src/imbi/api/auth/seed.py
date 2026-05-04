"""Permission and role seeding for authentication system."""

import logging
import typing

from imbi_common import graph

LOGGER = logging.getLogger(__name__)

# Standard permissions for all resource types
STANDARD_PERMISSIONS: list[tuple[str, str, str, str]] = [
    # User management
    ('user:create', 'user', 'create', 'Create new users'),
    ('user:read', 'user', 'read', 'View user information'),
    ('user:update', 'user', 'update', 'Update user information'),
    ('user:delete', 'user', 'delete', 'Delete users'),
    # Role management
    ('role:create', 'role', 'create', 'Create new roles'),
    ('role:read', 'role', 'read', 'View role information'),
    ('role:update', 'role', 'update', 'Update role information'),
    ('role:delete', 'role', 'delete', 'Delete roles'),
    # Organization management
    (
        'organization:create',
        'organization',
        'create',
        'Create organizations',
    ),
    (
        'organization:read',
        'organization',
        'read',
        'View organizations',
    ),
    (
        'organization:update',
        'organization',
        'update',
        'Update organizations',
    ),
    (
        'organization:delete',
        'organization',
        'delete',
        'Delete organizations',
    ),
    # Team management
    ('team:create', 'team', 'create', 'Create teams'),
    ('team:read', 'team', 'read', 'View teams'),
    ('team:update', 'team', 'update', 'Update teams'),
    ('team:delete', 'team', 'delete', 'Delete teams'),
    # Blueprint management
    ('blueprint:read', 'blueprint', 'read', 'View blueprints'),
    ('blueprint:write', 'blueprint', 'write', 'Create/update blueprints'),
    (
        'blueprint:delete',
        'blueprint',
        'delete',
        'Delete blueprints',
    ),
    # Project management
    ('project:create', 'project', 'create', 'Create projects'),
    ('project:read', 'project', 'read', 'View projects'),
    ('project:write', 'project', 'write', 'Update projects'),
    ('project:delete', 'project', 'delete', 'Delete projects'),
    # Link definition management
    (
        'link_definition:create',
        'link_definition',
        'create',
        'Create link definitions',
    ),
    (
        'link_definition:read',
        'link_definition',
        'read',
        'View link definitions',
    ),
    (
        'link_definition:write',
        'link_definition',
        'write',
        'Update link definitions',
    ),
    (
        'link_definition:delete',
        'link_definition',
        'delete',
        'Delete link definitions',
    ),
    # Environment management
    (
        'environment:create',
        'environment',
        'create',
        'Create environments',
    ),
    (
        'environment:read',
        'environment',
        'read',
        'View environments',
    ),
    (
        'environment:update',
        'environment',
        'update',
        'Update environments',
    ),
    (
        'environment:delete',
        'environment',
        'delete',
        'Delete environments',
    ),
    # Project type management
    (
        'project_type:create',
        'project_type',
        'create',
        'Create project types',
    ),
    (
        'project_type:read',
        'project_type',
        'read',
        'View project types',
    ),
    (
        'project_type:update',
        'project_type',
        'update',
        'Update project types',
    ),
    (
        'project_type:delete',
        'project_type',
        'delete',
        'Delete project types',
    ),
    # Third-party service management
    (
        'third_party_service:create',
        'third_party_service',
        'create',
        'Create third-party services',
    ),
    (
        'third_party_service:read',
        'third_party_service',
        'read',
        'View third-party services',
    ),
    (
        'third_party_service:update',
        'third_party_service',
        'update',
        'Update third-party services',
    ),
    (
        'third_party_service:delete',
        'third_party_service',
        'delete',
        'Delete third-party services',
    ),
    # Webhook management
    ('webhook:create', 'webhook', 'create', 'Create webhooks'),
    ('webhook:read', 'webhook', 'read', 'View webhooks'),
    ('webhook:update', 'webhook', 'update', 'Update webhooks'),
    ('webhook:delete', 'webhook', 'delete', 'Delete webhooks'),
    # Upload management
    ('upload:create', 'upload', 'create', 'Upload files'),
    (
        'upload:read',
        'upload',
        'read',
        'View and download uploads',
    ),
    ('upload:delete', 'upload', 'delete', 'Delete uploads'),
    # Service account management
    (
        'service_account:create',
        'service_account',
        'create',
        'Create service accounts',
    ),
    (
        'service_account:read',
        'service_account',
        'read',
        'View service accounts',
    ),
    (
        'service_account:update',
        'service_account',
        'update',
        'Update service accounts',
    ),
    (
        'service_account:delete',
        'service_account',
        'delete',
        'Delete service accounts',
    ),
    # Operations log management
    (
        'operations_log:create',
        'operations_log',
        'create',
        'Create operations log entries',
    ),
    (
        'operations_log:read',
        'operations_log',
        'read',
        'View operations log entries',
    ),
    (
        'operations_log:update',
        'operations_log',
        'update',
        'Update operations log entries',
    ),
    (
        'operations_log:delete',
        'operations_log',
        'delete',
        'Delete operations log entries',
    ),
    # Tag management
    ('tag:create', 'tag', 'create', 'Create tags'),
    ('tag:read', 'tag', 'read', 'View tags'),
    ('tag:write', 'tag', 'write', 'Update tags'),
    ('tag:delete', 'tag', 'delete', 'Delete tags'),
    # Note management
    ('note:create', 'note', 'create', 'Create project notes'),
    ('note:read', 'note', 'read', 'View project notes'),
    ('note:write', 'note', 'write', 'Update project notes'),
    ('note:delete', 'note', 'delete', 'Delete project notes'),
    # Auth provider (login-eligible ServiceApplication) management
    (
        'auth_providers:read',
        'auth_providers',
        'read',
        'View login auth provider configuration',
    ),
    (
        'auth_providers:write',
        'auth_providers',
        'write',
        'Create, update, and delete login auth provider configuration',
    ),
    # Scoring policy management
    (
        'scoring_policy:read',
        'scoring_policy',
        'read',
        'View scoring policies',
    ),
    (
        'scoring_policy:write',
        'scoring_policy',
        'write',
        'Create/update scoring policies',
    ),
    (
        'scoring_policy:delete',
        'scoring_policy',
        'delete',
        'Delete scoring policies',
    ),
    (
        'scoring_policy:rescore_all',
        'scoring_policy',
        'rescore_all',
        'Trigger bulk project rescore',
    ),
    # Note template management
    (
        'note_template:create',
        'note_template',
        'create',
        'Create note templates',
    ),
    (
        'note_template:read',
        'note_template',
        'read',
        'View note templates',
    ),
    (
        'note_template:write',
        'note_template',
        'write',
        'Update note templates',
    ),
    (
        'note_template:delete',
        'note_template',
        'delete',
        'Delete note templates',
    ),
    # Plugin management
    (
        'admin:plugins:read',
        'admin',
        'plugins:read',
        'View installed plugins',
    ),
    (
        'admin:plugins:manage',
        'admin',
        'plugins:manage',
        'Install and uninstall plugins',
    ),
    # Project plugin access
    (
        'project:configuration:read',
        'project',
        'configuration:read',
        'Read project configuration via plugins',
    ),
    (
        'project:configuration:read_secrets',
        'project',
        'configuration:read_secrets',
        'Read secret configuration values via plugins',
    ),
    (
        'project:configuration:write',
        'project',
        'configuration:write',
        'Write project configuration via plugins',
    ),
    (
        'project:logs:read',
        'project',
        'logs:read',
        'Read project logs via plugins',
    ),
]

# Default role definitions
DEFAULT_ROLES: list[tuple[str, str, str, int, list[str]]] = [
    (
        'admin',
        'Administrator',
        'Full system access with all permissions',
        1000,
        [perm[0] for perm in STANDARD_PERMISSIONS],  # All permissions
    ),
    (
        'developer',
        'Developer',
        'Standard developer access to projects and blueprints',
        500,
        [
            'blueprint:read',
            'blueprint:write',
            'project:create',
            'project:read',
            'project:write',
            'environment:read',
            'link_definition:read',
            'link_definition:write',
            'organization:read',
            'organization:update',
            'project_type:read',
            'team:read',
            'team:update',
            'user:read',
            'third_party_service:read',
            'third_party_service:update',
            'upload:create',
            'upload:read',
            'webhook:read',
            'webhook:update',
            'tag:create',
            'tag:read',
            'tag:write',
            'note:create',
            'note:read',
            'note:write',
            'note:delete',
            'note_template:read',
        ],
    ),
    (
        'readonly',
        'Read Only',
        'Read-only access to all resources',
        100,
        [
            'blueprint:read',
            'environment:read',
            'link_definition:read',
            'operations_log:read',
            'project:read',
            'project_type:read',
            'organization:read',
            'team:read',
            'third_party_service:read',
            'user:read',
            'role:read',
            'upload:read',
            'webhook:read',
            'tag:read',
            'note:read',
            'note_template:read',
        ],
    ),
]


async def seed_permissions(db: graph.Graph) -> int:
    """Seed standard permissions in a single batched query."""
    maps: list[str] = []
    params: dict[str, typing.Any] = {}
    for i, (name, resource_type, action, description) in enumerate(
        STANDARD_PERMISSIONS
    ):
        maps.append(
            f'{{{{name: {{p_n_{i}}}, resource_type: {{p_rt_{i}}},'
            f' action: {{p_a_{i}}}, description: {{p_d_{i}}}}}}}'
        )
        params[f'p_n_{i}'] = name
        params[f'p_rt_{i}'] = resource_type
        params[f'p_a_{i}'] = action
        params[f'p_d_{i}'] = description

    query: str = (
        'UNWIND [' + ', '.join(maps) + '] AS perm '
        'OPTIONAL MATCH (existing:Permission {{name: perm.name}}) '
        'WITH perm, existing '
        'MERGE (p:Permission {{name: perm.name}}) '
        'SET p.resource_type = perm.resource_type, '
        'p.action = perm.action, '
        'p.description = perm.description '
        'RETURN sum(CASE WHEN existing IS NULL THEN 1 ELSE 0 END) '
        'AS created'
    )
    records = await db.execute(query, params, columns=['created'])
    created_count = 0
    if records:
        raw = graph.parse_agtype(records[0].get('created'))
        created_count = int(raw or 0)
    LOGGER.info('Seeded %d permissions', created_count)
    return created_count


async def seed_default_roles(db: graph.Graph) -> int:
    """Seed default roles and GRANTS edges in a single batched query.

    Must run after ``seed_permissions``: the second UNWIND below does a
    ``MATCH (gp:Permission {{name: grant.perm}})`` that will silently
    produce no GRANTS edges if any referenced permission is missing.
    ``bootstrap_auth_system`` enforces this ordering.
    """
    role_maps: list[str] = []
    grant_maps: list[str] = []
    params: dict[str, typing.Any] = {}
    for i, (
        slug,
        name,
        description,
        priority,
        permission_names,
    ) in enumerate(DEFAULT_ROLES):
        role_maps.append(
            f'{{{{slug: {{r_s_{i}}}, name: {{r_n_{i}}},'
            f' description: {{r_d_{i}}}, priority: {{r_p_{i}}}}}}}'
        )
        params[f'r_s_{i}'] = slug
        params[f'r_n_{i}'] = name
        params[f'r_d_{i}'] = description
        params[f'r_p_{i}'] = priority
        for j, perm_name in enumerate(permission_names):
            grant_maps.append(
                f'{{{{slug: {{r_s_{i}}}, perm: {{g_{i}_{j}}}}}}}'
            )
            params[f'g_{i}_{j}'] = perm_name

    query: str = (
        'UNWIND [' + ', '.join(role_maps) + '] AS role '
        'OPTIONAL MATCH (existing:Role {{slug: role.slug}}) '
        'WITH role, existing '
        'MERGE (r:Role {{slug: role.slug}}) '
        'SET r.name = role.name, '
        'r.description = role.description, '
        'r.priority = role.priority, '
        'r.is_system = true '
        'WITH sum(CASE WHEN existing IS NULL THEN 1 ELSE 0 END) '
        'AS created '
        'UNWIND [' + ', '.join(grant_maps) + '] AS grant '
        'MATCH (gr:Role {{slug: grant.slug}}), '
        '(gp:Permission {{name: grant.perm}}) '
        'MERGE (gr)-[:GRANTS]->(gp) '
        'RETURN created LIMIT 1'
    )
    records = await db.execute(query, params, columns=['created'])
    created_count = 0
    if records:
        raw = graph.parse_agtype(records[0].get('created'))
        created_count = int(raw or 0)
    LOGGER.info('Seeded %d default roles', created_count)
    return created_count


async def seed_default_organization(
    db: graph.Graph,
    slug: str = 'default',
    name: str = 'Default',
) -> bool:
    """Seed the organization.

    Creates the organization using MERGE to ensure idempotency.

    Args:
        db: Graph database connection.
        slug: Organization slug (default: 'default').
        name: Organization display name (default: 'Default').

    Returns:
        True if the organization was newly created, False if it
        already existed.

    """
    # Check if the organization already exists
    check_query: typing.LiteralString = (
        'OPTIONAL MATCH '
        '(existing:Organization {{slug: {slug}}}) '
        'RETURN existing IS NULL AS is_new'
    )
    check_records = await db.execute(
        check_query,
        {'slug': slug},
        columns=['is_new'],
    )
    is_new = False
    if check_records:
        raw = graph.parse_agtype(check_records[0].get('is_new'))
        is_new = bool(raw)

    # Merge the organization node
    description = f'{name} organization'
    merge_query: typing.LiteralString = (
        'MERGE (o:Organization {{slug: {slug}}}) '
        'SET o.name = {name}, '
        'o.description = {description} '
        'RETURN o'
    )
    await db.execute(
        merge_query,
        {
            'slug': slug,
            'name': name,
            'description': description,
        },
    )

    if is_new:
        LOGGER.info('Created organization: %s (%s)', name, slug)
    else:
        LOGGER.info('Organization already exists: %s', slug)
    return is_new


async def bootstrap_auth_system(
    db: graph.Graph,
    org_slug: str = 'default',
    org_name: str = 'Default',
) -> dict[str, int | bool]:
    """Complete bootstrap of the authentication system.

    Seeds the organization, permissions, and default roles.
    This operation is idempotent and can be run multiple times
    safely.

    Args:
        db: Graph database connection.
        org_slug: Organization slug (default: 'default').
        org_name: Organization display name (default: 'Default').

    Returns:
        dict with keys:
            - 'organization': Whether the org was created
            - 'permissions': Number of permissions created
            - 'roles': Number of roles created

    """
    LOGGER.info('Starting authentication system bootstrap')

    org_created = await seed_default_organization(db, org_slug, org_name)
    permissions_created = await seed_permissions(db)
    roles_created = await seed_default_roles(db)

    result: dict[str, int | bool] = {
        'organization': org_created,
        'permissions': permissions_created,
        'roles': roles_created,
    }

    LOGGER.info(
        'Bootstrap complete: org created=%s, %d permissions, %d roles',
        org_created,
        permissions_created,
        roles_created,
    )

    return result


async def check_if_seeded(db: graph.Graph) -> bool:
    """Check if the authentication system has been fully seeded.

    Verifies that all standard permissions, default roles, and
    at least one organization exist before reporting the system
    as seeded.  This prevents a partial seed (e.g. permissions
    created but roles missing) from being treated as complete.

    Parameters:
        db: Graph database connection.

    Returns:
        bool: True if the full seed is present, False otherwise.
    """
    query: typing.LiteralString = """
    OPTIONAL MATCH (p:Permission)
    WITH count(p) AS perm_count
    OPTIONAL MATCH (r:Role)
    WITH perm_count, count(r) AS role_count
    OPTIONAL MATCH (o:Organization)
    RETURN perm_count, role_count, count(o) AS org_count
    """
    records = await db.execute(
        query,
        columns=['perm_count', 'role_count', 'org_count'],
    )
    if not records:
        return False
    perm_count = graph.parse_agtype(
        records[0].get('perm_count'),
    )
    role_count = graph.parse_agtype(
        records[0].get('role_count'),
    )
    org_count = graph.parse_agtype(
        records[0].get('org_count'),
    )
    expected_perms = len(STANDARD_PERMISSIONS)
    expected_roles = len(DEFAULT_ROLES)
    return (
        (perm_count or 0) >= expected_perms
        and (role_count or 0) >= expected_roles
        and (org_count or 0) > 0
    )
