"""User management endpoints."""

import datetime
import logging
import typing
from urllib import parse as urlparse

import fastapi
from imbi_common import models, neo4j
from imbi_common.auth import core
from neo4j import exceptions

from imbi_api.auth import permissions

LOGGER = logging.getLogger(__name__)

users_router = fastapi.APIRouter(prefix='/users', tags=['Users'])


@users_router.post('/', response_model=models.UserResponse, status_code=201)
async def create_user(
    user_create: models.UserCreate,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:create')),
    ],
) -> models.UserResponse:
    """
    Create a new user account.

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
        password_hash = core.hash_password(user_create.password)

    # Prevent non-admins from creating admin users
    if user_create.is_admin and not auth.user.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Only admins can create admin users',
        )

    # Create user model
    user = models.User(
        email=user_create.email,
        display_name=user_create.display_name,
        password_hash=password_hash,
        is_active=user_create.is_active,
        is_admin=user_create.is_admin,
        is_service_account=user_create.is_service_account,
        created_at=datetime.datetime.now(datetime.UTC),
    )

    try:
        await neo4j.create_node(user)
    except exceptions.ConstraintError as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'User with email {user.email!r} already exists',
        ) from e

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
    )


@users_router.get('/', response_model=list[models.UserResponse])
async def list_users(
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:read')),
    ],
    is_active: bool | None = None,
    is_admin: bool | None = None,
) -> list[models.UserResponse]:
    """
    Retrieve all users with optional filtering.

    Parameters:
        is_active (bool | None): If provided, filter by active status.
        is_admin (bool | None): If provided, filter by admin status.

    Returns:
        list[models.UserResponse]: Users ordered by email, without
            password hashes.
    """
    parameters = {}
    if is_active is not None:
        parameters['is_active'] = is_active
    if is_admin is not None:
        parameters['is_admin'] = is_admin

    users = []
    async for user in neo4j.fetch_nodes(
        models.User,
        parameters if parameters else None,
        order_by='email',
    ):
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
            )
        )
    return users


@users_router.get('/{email}', response_model=models.UserResponse)
async def get_user(
    email: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:read')),
    ],
) -> models.UserResponse:
    """
    Retrieve a user by email with loaded organization memberships.

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

    user = await neo4j.fetch_node(models.User, {'email': email})
    if user is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with email {email!r} not found',
        )

    # Load organization memberships via Cypher
    org_query = """
    MATCH (u:User {email: $email})-[m:MEMBER_OF]->(o:Organization)
    RETURN o.name AS org_name, o.slug AS org_slug, m.role AS role
    ORDER BY o.name
    """
    organizations: list[models.OrgMembership] = []
    async with neo4j.run(org_query, email=email) as result:
        records = await result.data()
        for record in records:
            organizations.append(
                models.OrgMembership(
                    organization_name=record['org_name'],
                    organization_slug=record['org_slug'],
                    role=record['role'],
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
        organizations=organizations,
    )


@users_router.put('/{email}', response_model=models.UserResponse)
async def update_user(
    email: str,
    user_update: models.UserCreate,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> models.UserResponse:
    """
    Update an existing user account.

    Parameters:
        email (str): Email from URL path.
        user_update (models.UserCreate): Updated user data.

    Returns:
        models.UserResponse: The updated user (without password_hash).

    Raises:
        fastapi.HTTPException: HTTP 400 if URL email doesn't match
            body email, or HTTP 404 if user not found.
    """
    # URL decode email in case it's percent-encoded
    email = urlparse.unquote(email)

    # Validate email matches
    if user_update.email != email:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Email in URL ({email!r}) must match email '
            f'in body ({user_update.email!r})',
        )

    # Verify user exists
    existing_user = await neo4j.fetch_node(models.User, {'email': email})
    if existing_user is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with email {email!r} not found',
        )

    # Prevent non-admins from modifying admin users
    if existing_user.is_admin and not auth.user.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Only admins can modify admin users',
        )

    # Prevent non-admins from setting is_admin
    if user_update.is_admin and not auth.user.is_admin:
        raise fastapi.HTTPException(
            status_code=403,
            detail='Only admins can grant admin privileges',
        )

    # Prevent users from deactivating themselves
    if email == auth.user.email and not user_update.is_active:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot deactivate your own account',
        )

    # Update password hash if password provided
    password_hash = existing_user.password_hash
    if user_update.password:
        password_hash = core.hash_password(user_update.password)

    # Create updated user model
    updated_user = models.User(
        email=user_update.email,
        display_name=user_update.display_name,
        password_hash=password_hash,
        is_active=user_update.is_active,
        is_admin=user_update.is_admin,
        is_service_account=user_update.is_service_account,
        created_at=existing_user.created_at,
        last_login=existing_user.last_login,
        avatar_url=existing_user.avatar_url,
    )

    await neo4j.upsert(updated_user, {'email': email})

    return models.UserResponse(
        email=updated_user.email,
        display_name=updated_user.display_name,
        is_active=updated_user.is_active,
        is_admin=updated_user.is_admin,
        is_service_account=updated_user.is_service_account,
        created_at=updated_user.created_at,
        last_login=updated_user.last_login,
        avatar_url=updated_user.avatar_url,
    )


@users_router.delete('/{email}', status_code=204)
async def delete_user(
    email: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:delete')),
    ],
) -> None:
    """
    Delete a user account.

    Parameters:
        email (str): Email of user to delete.

    Raises:
        fastapi.HTTPException: HTTP 400 if trying to delete yourself,
            or HTTP 404 if user not found.
    """
    # URL decode email in case it's percent-encoded
    email = urlparse.unquote(email)

    # Prevent self-deletion
    if email == auth.user.email:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot delete your own account',
        )

    deleted = await neo4j.delete_node(models.User, {'email': email})
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with email {email!r} not found',
        )


@users_router.post('/{email}/password', status_code=204)
async def change_password(
    email: str,
    password_change: models.PasswordChangeRequest,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> None:
    """
    Change a user's password.

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
    is_self = email == auth.user.email
    has_permission = 'user:update' in auth.permissions or auth.user.is_admin

    if not is_self and not has_permission:
        raise fastapi.HTTPException(
            status_code=403,
            detail="Cannot change another user's password",
        )

    # Fetch user
    user = await neo4j.fetch_node(models.User, {'email': email})
    if user is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with email {email!r} not found',
        )

    # Verify current password if user is changing their own password
    if is_self:
        if not password_change.current_password:
            raise fastapi.HTTPException(
                status_code=400,
                detail='Current password is required',
            )
        if not user.password_hash or not core.verify_password(
            password_change.current_password, user.password_hash
        ):
            raise fastapi.HTTPException(
                status_code=401,
                detail='Current password is incorrect',
            )

    # Update password
    user.password_hash = core.hash_password(password_change.new_password)
    await neo4j.upsert(user, {'email': email})


@users_router.post('/{email}/organizations', status_code=204)
async def add_to_organization(
    email: str,
    membership: dict[str, str],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> None:
    """
    Add a user to an organization with a role.

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
    MATCH (u:User {email: $email})
    MATCH (o:Organization {slug: $org_slug})
    MATCH (r:Role {slug: $role_slug})
    MERGE (u)-[m:MEMBER_OF]->(o)
    SET m.role = $role_slug
    RETURN u, o, r
    """
    async with neo4j.run(
        query,
        email=email,
        org_slug=org_slug,
        role_slug=role_slug,
    ) as result:
        records = await result.data()
        if not records:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'User {email!r}, organization {org_slug!r},'
                f' or role {role_slug!r} not found',
            )


@users_router.put(
    '/{email}/organizations/{org_slug}',
    status_code=204,
)
async def update_organization_role(
    email: str,
    org_slug: str,
    role_data: dict[str, str],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> None:
    """
    Change a user's role in an organization.

    Parameters:
        email (str): Email of user.
        org_slug (str): Organization slug.
        role_data (dict): Dictionary with 'role_slug' key.

    Raises:
        fastapi.HTTPException: HTTP 400 if role_slug missing,
            HTTP 404 if membership or role not found.
    """
    email = urlparse.unquote(email)

    role_slug = role_data.get('role_slug')
    if not role_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='role_slug is required',
        )

    query = """
    MATCH (u:User {email: $email})-[m:MEMBER_OF]->
          (o:Organization {slug: $org_slug})
    MATCH (r:Role {slug: $role_slug})
    SET m.role = $role_slug
    RETURN u, o, r
    """
    async with neo4j.run(
        query,
        email=email,
        org_slug=org_slug,
        role_slug=role_slug,
    ) as result:
        records = await result.data()
        if not records:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'Membership for {email!r} in {org_slug!r}'
                f' or role {role_slug!r} not found',
            )


@users_router.delete(
    '/{email}/organizations/{org_slug}',
    status_code=204,
)
async def remove_from_organization(
    email: str,
    org_slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> None:
    """
    Remove a user from an organization.

    Parameters:
        email (str): Email of user.
        org_slug (str): Organization slug.

    Raises:
        fastapi.HTTPException: HTTP 404 if membership not found.
    """
    email = urlparse.unquote(email)

    query = """
    MATCH (u:User {email: $email})-[m:MEMBER_OF]->
          (o:Organization {slug: $org_slug})
    DELETE m
    RETURN count(m) AS deleted
    """
    async with neo4j.run(
        query,
        email=email,
        org_slug=org_slug,
    ) as result:
        records = await result.data()
        if not records or records[0].get('deleted', 0) == 0:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'User {email!r} is not a member of '
                f'organization {org_slug!r}',
            )
