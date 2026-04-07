"""Permission and role seeding for authentication system."""

import logging
import typing

from imbi_common import neo4j

from imbi_api import models

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
    ('organization:create', 'organization', 'create', 'Create organizations'),
    ('organization:read', 'organization', 'read', 'View organizations'),
    ('organization:update', 'organization', 'update', 'Update organizations'),
    ('organization:delete', 'organization', 'delete', 'Delete organizations'),
    # Team management
    ('team:create', 'team', 'create', 'Create teams'),
    ('team:read', 'team', 'read', 'View teams'),
    ('team:update', 'team', 'update', 'Update teams'),
    ('team:delete', 'team', 'delete', 'Delete teams'),
    # Blueprint management
    ('blueprint:read', 'blueprint', 'read', 'View blueprints'),
    ('blueprint:write', 'blueprint', 'write', 'Create/update blueprints'),
    ('blueprint:delete', 'blueprint', 'delete', 'Delete blueprints'),
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
    ('environment:create', 'environment', 'create', 'Create environments'),
    ('environment:read', 'environment', 'read', 'View environments'),
    ('environment:update', 'environment', 'update', 'Update environments'),
    ('environment:delete', 'environment', 'delete', 'Delete environments'),
    # Project type management
    ('project_type:create', 'project_type', 'create', 'Create project types'),
    ('project_type:read', 'project_type', 'read', 'View project types'),
    ('project_type:update', 'project_type', 'update', 'Update project types'),
    ('project_type:delete', 'project_type', 'delete', 'Delete project types'),
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
    ('upload:read', 'upload', 'read', 'View and download uploads'),
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
            'project:read',
            'project_type:read',
            'organization:read',
            'team:read',
            'third_party_service:read',
            'user:read',
            'role:read',
            'upload:read',
            'webhook:read',
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
            slug=slug,
            name=name,
            description=description,
            priority=priority,
            is_system=True,
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


async def seed_default_organization(
    slug: str = 'default',
    name: str = 'Default',
) -> bool:
    """Seed the organization.

    Creates the organization using MERGE to ensure idempotency.

    Args:
        slug: Organization slug (default: 'default').
        name: Organization display name (default: 'Default').

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
        slug=slug,
        name=name,
        description=f'{name} organization',
    ) as result:
        records = await result.data()
        created = bool(records and records[0].get('is_new'))

    if created:
        LOGGER.info('Created organization: %s (%s)', name, slug)
    else:
        LOGGER.info('Organization already exists: %s', slug)
    return created


async def bootstrap_auth_system(
    org_slug: str = 'default',
    org_name: str = 'Default',
) -> dict[str, int | bool]:
    """Complete bootstrap of the authentication system.

    Seeds the organization, permissions, and default roles.
    This operation is idempotent and can be run multiple times safely.

    Args:
        org_slug: Organization slug (default: 'default').
        org_name: Organization display name (default: 'Default').

    Returns:
        dict with keys:
            - 'organization': Whether the org was created
            - 'permissions': Number of permissions created
            - 'roles': Number of roles created

    """
    LOGGER.info('Starting authentication system bootstrap')

    org_created = await seed_default_organization(org_slug, org_name)
    permissions_created = await seed_permissions()
    roles_created = await seed_default_roles()

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
