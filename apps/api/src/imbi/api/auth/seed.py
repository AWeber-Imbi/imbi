"""Permission and role seeding for authentication system."""

import logging
import typing

from imbi_common import models, neo4j

LOGGER = logging.getLogger(__name__)

# Standard permissions for all resource types
STANDARD_PERMISSIONS: list[tuple[str, str, str, str]] = [
    # User management
    ('user:create', 'user', 'create', 'Create new users'),
    ('user:read', 'user', 'read', 'View user information'),
    ('user:update', 'user', 'update', 'Update user information'),
    ('user:delete', 'user', 'delete', 'Delete users'),
    # Group management
    ('group:create', 'group', 'create', 'Create new groups'),
    ('group:read', 'group', 'read', 'View group information'),
    ('group:update', 'group', 'update', 'Update group information'),
    ('group:delete', 'group', 'delete', 'Delete groups'),
    # Role management
    ('role:create', 'role', 'create', 'Create new roles'),
    ('role:read', 'role', 'read', 'View role information'),
    ('role:update', 'role', 'update', 'Update role information'),
    ('role:delete', 'role', 'delete', 'Delete roles'),
    # Organization management
    ('organization:create', 'organization', 'create', 'Create organizations'),
    ('organization:read', 'organization', 'read', 'View organizations'),
    ('organization:update', 'organization', 'update', 'Update organizations'),
    ('organization:delete', 'organization', 'delete', 'Delete organizations'),
    # Blueprint management
    ('blueprint:read', 'blueprint', 'read', 'View blueprints'),
    ('blueprint:write', 'blueprint', 'write', 'Create/update blueprints'),
    ('blueprint:delete', 'blueprint', 'delete', 'Delete blueprints'),
    # Project management
    ('project:read', 'project', 'read', 'View projects'),
    ('project:write', 'project', 'write', 'Create/update projects'),
    ('project:delete', 'project', 'delete', 'Delete projects'),
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
            'project:read',
            'project:write',
            'organization:read',
            'organization:update',
            'group:read',
            'user:read',
        ],
    ),
    (
        'readonly',
        'Read Only',
        'Read-only access to all resources',
        100,
        [
            'blueprint:read',
            'project:read',
            'organization:read',
            'group:read',
            'user:read',
            'role:read',
        ],
    ),
]


async def seed_permissions() -> int:
    """
    Seed standard permissions into the database.

    Uses MERGE to make the operation idempotent - running multiple times
    will not create duplicates.

    Returns:
        int: Number of permissions created (not updated).
    """
    created_count = 0

    for name, resource_type, action, description in STANDARD_PERMISSIONS:
        # Create Permission model
        permission = models.Permission(
            name=name,
            resource_type=resource_type,
            action=action,
            description=description,
        )

        # Use MERGE to avoid duplicates
        query = """
        OPTIONAL MATCH (existing:Permission {name: $name})
        WITH existing IS NULL AS is_new
        MERGE (p:Permission {name: $name})
        ON CREATE SET
            p.resource_type = $resource_type,
            p.action = $action,
            p.description = $description
        ON MATCH SET
            p.resource_type = $resource_type,
            p.action = $action,
            p.description = $description
        RETURN p, is_new
        """

        async with neo4j.run(
            query,
            name=permission.name,
            resource_type=permission.resource_type,
            action=permission.action,
            description=permission.description,
        ) as result:
            records = await result.data()
            if records and records[0].get('is_new'):
                created_count += 1

    LOGGER.info('Seeded %d permissions', created_count)
    return created_count


async def seed_default_roles() -> int:
    """
    Seed default roles (admin, developer, readonly) into the database.

    Uses MERGE to make the operation idempotent.

    Returns:
        int: Number of roles created (not updated).
    """
    created_count = 0

    for slug, name, description, priority, permission_names in DEFAULT_ROLES:
        # Create Role model
        role = models.Role(
            name=name,
            slug=slug,
            description=description,
            priority=priority,
            is_system=True,  # Mark as system role
        )

        # Use MERGE to avoid duplicates
        role_query = """
        OPTIONAL MATCH (existing:Role {slug: $slug})
        WITH existing IS NULL AS is_new
        MERGE (r:Role {slug: $slug})
        ON CREATE SET
            r.name = $name,
            r.description = $description,
            r.priority = $priority,
            r.is_system = $is_system
        ON MATCH SET
            r.name = $name,
            r.description = $description,
            r.priority = $priority,
            r.is_system = $is_system
        RETURN r, is_new
        """

        async with neo4j.run(
            query=role_query,
            slug=role.slug,
            name=role.name,
            description=role.description,
            priority=role.priority,
            is_system=role.is_system,
        ) as result:
            records = await result.data()
            if records and records[0].get('is_new'):
                created_count += 1

        # Grant permissions to role
        for perm_name in permission_names:
            perm_query = """
            MATCH (r:Role {slug: $slug})
            MATCH (p:Permission {name: $perm_name})
            MERGE (r)-[:GRANTS]->(p)
            """
            async with neo4j.run(
                query=perm_query, slug=slug, perm_name=perm_name
            ) as result:
                await result.consume()

    LOGGER.info('Seeded %d default roles', created_count)
    return created_count


async def seed_default_organization() -> bool:
    """Seed the default organization.

    Creates a 'Default' organization using MERGE to ensure idempotency.

    Returns:
        True if the organization was newly created, False if it
        already existed.

    """
    query: typing.LiteralString = """
    OPTIONAL MATCH (existing:Organization {slug: $slug})
    WITH existing IS NULL AS is_new
    MERGE (o:Organization {slug: $slug})
    ON CREATE SET
        o.name = $name,
        o.description = $description
    ON MATCH SET
        o.name = $name,
        o.description = $description
    RETURN o, is_new
    """
    async with neo4j.run(
        query,
        slug='default',
        name='Default',
        description='Default organization',
    ) as result:
        records = await result.data()
        created = bool(records and records[0].get('is_new'))

    if created:
        LOGGER.info('Created default organization')
    else:
        LOGGER.info('Default organization already exists')
    return created


async def seed_default_group() -> bool:
    """Seed the default 'Users' group within the default organization.

    Creates a 'Users' group and links it to the default organization
    via a MANAGED_BY relationship. Uses MERGE for idempotency.

    The default organization must exist before calling this function.

    Returns:
        True if the group was newly created, False if it already
        existed.

    """
    query: typing.LiteralString = """
    MATCH (o:Organization {slug: $org_slug})
    OPTIONAL MATCH (existing:Group {slug: $group_slug})
    WITH o, existing IS NULL AS is_new
    MERGE (g:Group {slug: $group_slug})
    ON CREATE SET
        g.name = $group_name,
        g.description = $group_description
    ON MATCH SET
        g.name = $group_name,
        g.description = $group_description
    MERGE (g)-[:MANAGED_BY]->(o)
    RETURN g, is_new
    """
    async with neo4j.run(
        query,
        org_slug='default',
        group_slug='users',
        group_name='Users',
        group_description='Default users group',
    ) as result:
        records = await result.data()
        created = bool(records and records[0].get('is_new'))

    if created:
        LOGGER.info('Created default users group')
    else:
        LOGGER.info('Default users group already exists')
    return created


async def bootstrap_auth_system() -> dict[str, int | bool]:
    """Complete bootstrap of the authentication system.

    Seeds permissions, creates default roles, the default organization,
    and the default users group. This operation is idempotent and can
    be run multiple times safely.

    Returns:
        dict with keys:
            - 'permissions': Number of permissions created
            - 'roles': Number of roles created
            - 'organization': Whether the default org was created
            - 'group': Whether the default group was created

    """
    LOGGER.info('Starting authentication system bootstrap')

    permissions_created = await seed_permissions()
    roles_created = await seed_default_roles()
    org_created = await seed_default_organization()
    group_created = await seed_default_group()

    result: dict[str, int | bool] = {
        'permissions': permissions_created,
        'roles': roles_created,
        'organization': org_created,
        'group': group_created,
    }

    LOGGER.info(
        'Bootstrap complete: %d permissions, %d roles, '
        'org created=%s, group created=%s',
        permissions_created,
        roles_created,
        org_created,
        group_created,
    )

    return result


async def check_if_seeded() -> bool:
    """
    Check if the authentication system has already been seeded.

    Returns:
        bool: True if permissions exist in the database, False otherwise.
    """
    query = """
    MATCH (p:Permission)
    RETURN count(p) AS count
    """

    async with neo4j.run(query) as result:
        records = await result.data()
        if records and records[0].get('count', 0) > 0:
            return True

    return False
