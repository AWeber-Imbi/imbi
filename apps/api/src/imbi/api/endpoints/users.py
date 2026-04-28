"""User management endpoints."""

import logging
import typing
from urllib import parse as urlparse

import fastapi
import psycopg.errors
from imbi_common import graph

from imbi_api import models
from imbi_api import patch as json_patch
from imbi_api.auth import password, permissions
from imbi_api.endpoints import _helpers

LOGGER = logging.getLogger(__name__)

users_router = fastapi.APIRouter(prefix='/users', tags=['Users'])


@users_router.post('/', response_model=models.UserResponse, status_code=201)
async def create_user(
    user_create: models.UserCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:create')),
    ],
) -> models.UserResponse:
    """Create a new user account.

    Parameters:
        user_create (models.UserCreate): User creation data including
            optional password. If password is None, creates an OAuth-only
            user.

    Returns:
        models.UserResponse: The created user (without password_hash).

    Raises:
        fastapi.HTTPException: HTTP 409 if email already exists.

    """
    # Hash password if provided
    password_hash = None
    if user_create.password:
        password_hash = password.hash_password(user_create.password)

    # Prevent non-admins from creating admin users
    if user_create.is_admin and not auth.require_user.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Only admins can create admin users',
        )

    # Prevent service accounts from having passwords
    if user_create.is_service_account and user_create.password:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Service accounts cannot have passwords',
        )

    # Prevent service accounts from being admins
    if user_create.is_service_account and user_create.is_admin:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Service accounts cannot be admins',
        )

    # Create user model
    user = models.User(
        email=user_create.email,
        display_name=user_create.display_name,
        password_hash=password_hash,
        is_active=user_create.is_active,
        is_admin=user_create.is_admin,
        is_service_account=user_create.is_service_account,
        email_notifications=user_create.email_notifications,
    )

    # Check if user already exists before creating to avoid
    # silent upsert (merge would overwrite a pre-existing user)
    existing = await db.match(
        models.User,
        {'email': user.email},
    )
    if existing:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'User with email {user.email!r} already exists'),
        )

    try:
        await db.create(user)
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(f'User with email {user.email!r} already exists'),
        ) from e

    # Create MEMBER_OF relationship to organization with role
    membership_query = """
    MATCH (u:User {{email: {email}}}),
          (o:Organization {{slug: {org_slug}}}),
          (r:Role {{slug: {role_slug}}})
    MERGE (u)-[m:MEMBER_OF]->(o)
    SET m.role = {role_slug}
    RETURN o.name, o.slug, r.slug
    """
    records = await db.execute(
        membership_query,
        {
            'email': user.email,
            'org_slug': user_create.organization_slug,
            'role_slug': user_create.role_slug,
        },
        columns=['org_name', 'org_slug', 'role'],
    )

    organizations: list[models.OrgMembership] = []
    if not records:
        # Rollback: delete the user node
        await db.delete(user)
        raise fastapi.HTTPException(
            status_code=404,
            detail=(
                f'Organization {user_create.organization_slug!r}'
                f' or role {user_create.role_slug!r} not found'
            ),
        )
    for record in records:
        organizations.append(
            models.OrgMembership(
                organization_name=graph.parse_agtype(
                    record['org_name'],
                ),
                organization_slug=graph.parse_agtype(
                    record['org_slug'],
                ),
                role=graph.parse_agtype(record['role']),
            )
        )

    # Return response model without password hash
    return models.UserResponse(
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_admin=user.is_admin,
        is_service_account=user.is_service_account,
        created_at=user.created_at,
        last_login=user.last_login,
        avatar_url=user.avatar_url,
        email_notifications=user.email_notifications,
        organizations=organizations,
    )


@users_router.get('/', response_model=list[models.UserResponse])
async def list_users(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:read')),
    ],
    is_active: bool | None = None,
    is_admin: bool | None = None,
) -> list[models.UserResponse]:
    """Retrieve all users with optional filtering.

    Parameters:
        is_active (bool | None): If provided, filter by active status.
        is_admin (bool | None): If provided, filter by admin status.

    Returns:
        list[models.UserResponse]: Users ordered by email, without
            password hashes.

    """
    parameters: dict[str, typing.Any] = {}
    if is_active is not None:
        parameters['is_active'] = is_active
    if is_admin is not None:
        parameters['is_admin'] = is_admin

    nodes = await db.match(
        models.User,
        parameters if parameters else None,
        order_by='email',
    )

    users: list[models.UserResponse] = []
    for user in nodes:
        users.append(
            models.UserResponse(
                email=user.email,
                display_name=user.display_name,
                is_active=user.is_active,
                is_admin=user.is_admin,
                is_service_account=user.is_service_account,
                created_at=user.created_at,
                last_login=user.last_login,
                avatar_url=user.avatar_url,
                email_notifications=user.email_notifications,
            )
        )
    return users


@users_router.get('/{email}', response_model=models.UserResponse)
async def get_user(
    email: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:read')),
    ],
) -> models.UserResponse:
    """Retrieve a user by email with loaded organization memberships.

    Parameters:
        email (str): Email address of the user to retrieve.

    Returns:
        models.UserResponse: User with loaded organizations, without
            password hash.

    Raises:
        fastapi.HTTPException: HTTP 404 if user not found.

    """
    # URL decode email in case it's percent-encoded
    email = urlparse.unquote(email)

    results = await db.match(models.User, {'email': email})
    if not results:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with email {email!r} not found',
        )
    user = results[0]

    # Load organization memberships via Cypher
    org_query = """
    MATCH (u:User {{email: {email}}})-[m:MEMBER_OF]->(o:Organization)
    RETURN o.name, o.slug, m.role
    ORDER BY o.name
    """
    org_records = await db.execute(
        org_query,
        {'email': email},
        columns=['org_name', 'org_slug', 'role'],
    )

    organizations: list[models.OrgMembership] = []
    for record in org_records:
        organizations.append(
            models.OrgMembership(
                organization_name=graph.parse_agtype(
                    record['org_name'],
                ),
                organization_slug=graph.parse_agtype(
                    record['org_slug'],
                ),
                role=graph.parse_agtype(record['role']),
            )
        )

    return models.UserResponse(
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_admin=user.is_admin,
        is_service_account=user.is_service_account,
        created_at=user.created_at,
        last_login=user.last_login,
        avatar_url=user.avatar_url,
        email_notifications=user.email_notifications,
        organizations=organizations,
    )


@users_router.patch('/{email}', response_model=models.UserResponse)
async def patch_user(
    email: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> models.UserResponse:
    """Partially update a user using JSON Patch (RFC 6902).

    Parameters:
        email: Email from URL path (percent-encoded).
        operations: JSON Patch operations.

    Returns:
        The updated user.

    Raises:
        fastapi.HTTPException: HTTP 400 if invalid patch, read-only
            path, or business logic violation. HTTP 403 if insufficient
            privileges. HTTP 404 if user not found. HTTP 422 if patch
            test failed.

    """
    email = urlparse.unquote(email)

    results = await db.match(models.User, {'email': email})
    if not results:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with email {email!r} not found',
        )
    existing_user = results[0]

    # Prevent non-admins from modifying admin users
    if existing_user.is_admin and not auth.require_user.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Only admins can modify admin users',
        )

    # Build patchable document (exclude password_hash and timestamps)
    current: dict[str, typing.Any] = {
        'email': existing_user.email,
        'display_name': existing_user.display_name,
        'is_active': existing_user.is_active,
        'is_admin': existing_user.is_admin,
        'is_service_account': existing_user.is_service_account,
        'email_notifications': existing_user.email_notifications,
    }

    patched = json_patch.apply_patch(
        current,
        operations,
        readonly_paths=json_patch.READONLY_PATHS | frozenset(['/email']),
    )

    # Prevent non-admins from granting admin privileges
    if patched.get('is_admin') and not auth.require_user.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Only admins can grant admin privileges',
        )

    # Prevent users from deactivating themselves
    if email == auth.require_user.email and not patched.get('is_active', True):
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot deactivate your own account',
        )

    # Prevent service accounts from being admins
    if patched.get('is_service_account') and patched.get('is_admin'):
        raise fastapi.HTTPException(
            status_code=400,
            detail='Service accounts cannot be admins',
        )

    # Preserve existing password_hash; clear if becoming service account
    password_hash = existing_user.password_hash
    if patched.get('is_service_account', existing_user.is_service_account):
        password_hash = None

    updated_user = models.User(
        email=patched['email'],
        display_name=patched.get('display_name', existing_user.display_name),
        password_hash=password_hash,
        is_active=patched.get('is_active', existing_user.is_active),
        is_admin=patched.get('is_admin', existing_user.is_admin),
        is_service_account=patched.get(
            'is_service_account', existing_user.is_service_account
        ),
        email_notifications=patched.get(
            'email_notifications', existing_user.email_notifications
        ),
        created_at=existing_user.created_at,
        last_login=existing_user.last_login,
        avatar_url=existing_user.avatar_url,
    )

    await db.merge(updated_user, match_on=['email'])

    return models.UserResponse(
        email=updated_user.email,
        display_name=updated_user.display_name,
        is_active=updated_user.is_active,
        is_admin=updated_user.is_admin,
        is_service_account=updated_user.is_service_account,
        created_at=updated_user.created_at,
        last_login=updated_user.last_login,
        avatar_url=updated_user.avatar_url,
        email_notifications=updated_user.email_notifications,
    )


@users_router.delete('/{email}', status_code=204)
async def delete_user(
    email: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:delete')),
    ],
) -> None:
    """Delete a user account.

    Parameters:
        email (str): Email of user to delete.

    Raises:
        fastapi.HTTPException: HTTP 400 if trying to delete yourself,
            or HTTP 404 if user not found.

    """
    # URL decode email in case it's percent-encoded
    email = urlparse.unquote(email)

    # Prevent self-deletion
    if email == auth.require_user.email:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot delete your own account',
        )

    records = await db.execute(
        'MATCH (n:User {{email: {email}}}) DETACH DELETE n RETURN n',
        {'email': email},
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with email {email!r} not found',
        )


@users_router.post('/{email}/password', status_code=204)
async def change_password(
    email: str,
    password_change: models.PasswordChangeRequest,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.get_current_user),
    ],
) -> None:
    """Change a user's password.

    Parameters:
        email (str): Email of user whose password to change.
        password_change (models.PasswordChangeRequest): Password change
            data with current and new passwords.

    Raises:
        fastapi.HTTPException: HTTP 401 if current password is wrong
            (non-admin), HTTP 403 if not self or admin, or HTTP 404
            if user not found.

    """
    # URL decode email in case it's percent-encoded
    email = urlparse.unquote(email)

    # Check permission: must be self or have user:update permission
    is_self = email == auth.require_user.email
    has_permission = (
        'user:update' in auth.permissions or auth.require_user.is_admin
    )

    if not is_self and not has_permission:
        raise fastapi.HTTPException(
            status_code=403,
            detail="Cannot change another user's password",
        )

    # Fetch user
    results = await db.match(models.User, {'email': email})
    if not results:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with email {email!r} not found',
        )
    user = results[0]

    # Prevent password changes for service accounts
    if user.is_service_account:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Service accounts cannot have passwords',
        )

    # Verify current password if user is changing their own password
    if is_self:
        if not password_change.current_password:
            raise fastapi.HTTPException(
                status_code=400,
                detail='Current password is required',
            )
        if not user.password_hash or not password.verify_password(
            password_change.current_password, user.password_hash
        ):
            raise fastapi.HTTPException(
                status_code=401,
                detail='Current password is incorrect',
            )

    # Update password
    user.password_hash = password.hash_password(
        password_change.new_password,
    )
    await db.merge(user, match_on=['email'])


@users_router.post('/{email}/organizations', status_code=204)
async def add_to_organization(
    email: str,
    membership: dict[str, str],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> None:
    """Add a user to an organization with a role.

    Parameters:
        email (str): Email of user to add.
        membership (dict): Dictionary with 'organization_slug' and
            'role_slug' keys.

    Raises:
        fastapi.HTTPException: HTTP 400 if required fields missing,
            HTTP 404 if user, organization, or role not found.

    """
    email = urlparse.unquote(email)

    org_slug = membership.get('organization_slug')
    role_slug = membership.get('role_slug')
    if not org_slug or not role_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='organization_slug and role_slug are required',
        )

    query = """
    MATCH (u:User {{email: {email}}}),
          (o:Organization {{slug: {org_slug}}}),
          (r:Role {{slug: {role_slug}}})
    MERGE (u)-[m:MEMBER_OF]->(o)
    SET m.role = {role_slug}
    RETURN u, o, r
    """
    records = await db.execute(
        query,
        {
            'email': email,
            'org_slug': org_slug,
            'role_slug': role_slug,
        },
        columns=['u', 'o', 'r'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User {email!r}, organization {org_slug!r},'
            f' or role {role_slug!r} not found',
        )


@users_router.patch(
    '/{email}/organizations/{org_slug}',
    status_code=204,
)
async def update_organization_role(
    email: str,
    org_slug: str,
    operations: list[json_patch.PatchOperation],
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> None:
    """Change a user's role in an organization via JSON Patch.

    Parameters:
        email (str): Email of user.
        org_slug (str): Organization slug.
        operations (list): JSON Patch operations. Exactly one
            ``replace`` or ``add`` op targeting ``/role_slug``.

    Raises:
        fastapi.HTTPException: HTTP 400 on malformed patch, HTTP 404
            if membership or role not found.

    """
    email = urlparse.unquote(email)
    role_slug = _helpers.extract_role_slug(operations)
    await _helpers.update_membership_role(
        db,
        principal_label='User',
        principal_match_prop='email',
        principal_value=email,
        org_slug=org_slug,
        role_slug=role_slug,
    )


@users_router.delete(
    '/{email}/organizations/{org_slug}',
    status_code=204,
)
async def remove_from_organization(
    email: str,
    org_slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> None:
    """Remove a user from an organization.

    Parameters:
        email (str): Email of user.
        org_slug (str): Organization slug.

    Raises:
        fastapi.HTTPException: HTTP 404 if membership not found.

    """
    email = urlparse.unquote(email)

    query = """
    MATCH (u:User {{email: {email}}})-[m:MEMBER_OF]->
          (o:Organization {{slug: {org_slug}}})
    DELETE m
    RETURN m
    """
    records = await db.execute(
        query,
        {
            'email': email,
            'org_slug': org_slug,
        },
        columns=['m'],
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User {email!r} is not a member of '
            f'organization {org_slug!r}',
        )
