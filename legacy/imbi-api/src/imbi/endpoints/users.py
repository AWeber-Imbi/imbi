"""User management endpoints."""

import datetime
import logging
import typing

import fastapi
from neo4j import exceptions

from imbi import models, neo4j
from imbi.auth import core, permissions

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
        fastapi.HTTPException: HTTP 409 if username or email already
            exists.
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
        username=user_create.username,
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
            detail=f'User with username {user.username!r} already exists',
        ) from e

    # Return response model without password hash
    return models.UserResponse(
        username=user.username,
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
        list[models.UserResponse]: Users ordered by username, without
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
        order_by='username',
    ):
        users.append(
            models.UserResponse(
                username=user.username,
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


@users_router.get('/{username}', response_model=models.UserResponse)
async def get_user(
    username: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:read')),
    ],
) -> models.UserResponse:
    """
    Retrieve a user by username with loaded relationships.

    Parameters:
        username (str): Username of the user to retrieve.

    Returns:
        models.UserResponse: User with loaded groups and roles, without
            password hash.

    Raises:
        fastapi.HTTPException: HTTP 404 if user not found.
    """
    user = await neo4j.fetch_node(models.User, {'username': username})
    if user is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with username {username!r} not found',
        )

    # Load relationships
    await neo4j.refresh_relationship(user, 'groups')
    await neo4j.refresh_relationship(user, 'roles')

    return models.UserResponse(
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_admin=user.is_admin,
        is_service_account=user.is_service_account,
        created_at=user.created_at,
        last_login=user.last_login,
        avatar_url=user.avatar_url,
        groups=user.groups,
        roles=user.roles,
    )


@users_router.put('/{username}', response_model=models.UserResponse)
async def update_user(
    username: str,
    user_update: models.UserCreate,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> models.UserResponse:
    """
    Update an existing user account.

    Parameters:
        username (str): Username from URL path.
        user_update (models.UserCreate): Updated user data.

    Returns:
        models.UserResponse: The updated user (without password_hash).

    Raises:
        fastapi.HTTPException: HTTP 400 if URL username doesn't match
            body username, or HTTP 404 if user not found.
    """
    # Validate username matches
    if user_update.username != username:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f'Username in URL ({username!r}) must match username '
            f'in body ({user_update.username!r})',
        )

    # Verify user exists
    existing_user = await neo4j.fetch_node(models.User, {'username': username})
    if existing_user is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with username {username!r} not found',
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
    if username == auth.user.username and not user_update.is_active:
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
        username=user_update.username,
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

    await neo4j.upsert(updated_user, {'username': username})

    return models.UserResponse(
        username=updated_user.username,
        email=updated_user.email,
        display_name=updated_user.display_name,
        is_active=updated_user.is_active,
        is_admin=updated_user.is_admin,
        is_service_account=updated_user.is_service_account,
        created_at=updated_user.created_at,
        last_login=updated_user.last_login,
        avatar_url=updated_user.avatar_url,
    )


@users_router.delete('/{username}', status_code=204)
async def delete_user(
    username: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:delete')),
    ],
) -> None:
    """
    Delete a user account.

    Parameters:
        username (str): Username of user to delete.

    Raises:
        fastapi.HTTPException: HTTP 400 if trying to delete yourself,
            or HTTP 404 if user not found.
    """
    # Prevent self-deletion
    if username == auth.user.username:
        raise fastapi.HTTPException(
            status_code=400,
            detail='Cannot delete your own account',
        )

    deleted = await neo4j.delete_node(models.User, {'username': username})
    if not deleted:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with username {username!r} not found',
        )


@users_router.post('/{username}/password', status_code=204)
async def change_password(
    username: str,
    password_change: models.PasswordChangeRequest,
    auth: typing.Annotated[
        permissions.AuthContext, fastapi.Depends(permissions.get_current_user)
    ],
) -> None:
    """
    Change a user's password.

    Parameters:
        username (str): Username whose password to change.
        password_change (models.PasswordChangeRequest): Password change
            data with current and new passwords.

    Raises:
        fastapi.HTTPException: HTTP 401 if current password is wrong
            (non-admin), HTTP 403 if not self or admin, or HTTP 404
            if user not found.
    """
    # Check permission: must be self or have user:update permission
    is_self = username == auth.user.username
    has_permission = 'user:update' in auth.permissions or auth.user.is_admin

    if not is_self and not has_permission:
        raise fastapi.HTTPException(
            status_code=403,
            detail="Cannot change another user's password",
        )

    # Fetch user
    user = await neo4j.fetch_node(models.User, {'username': username})
    if user is None:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'User with username {username!r} not found',
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
    await neo4j.upsert(user, {'username': username})


@users_router.post('/{username}/roles', status_code=204)
async def grant_role(
    username: str,
    role_grant: dict[str, str],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> None:
    """
    Grant a role to a user.

    Parameters:
        username (str): Username to grant role to.
        role_grant (dict): Dictionary with 'role_slug' key.

    Raises:
        fastapi.HTTPException: HTTP 404 if user or role not found.
    """
    role_slug = role_grant.get('role_slug')
    if not role_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='role_slug is required',
        )

    query = """
    MATCH (u:User {username: $username})
    MATCH (r:Role {slug: $role_slug})
    MERGE (u)-[:HAS_ROLE]->(r)
    RETURN u, r
    """

    async with neo4j.run(
        query, username=username, role_slug=role_slug
    ) as result:
        records = await result.data()
        if not records:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'User {username!r} or role {role_slug!r} not found',
            )


@users_router.delete('/{username}/roles/{role_slug}', status_code=204)
async def revoke_role(
    username: str,
    role_slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> None:
    """
    Revoke a role from a user.

    Parameters:
        username (str): Username to revoke role from.
        role_slug (str): Slug of role to revoke.

    Raises:
        fastapi.HTTPException: HTTP 404 if relationship doesn't exist.
    """
    query = """
    MATCH (u:User {username: $username})-[r:HAS_ROLE]->
          (role:Role {slug: $role_slug})
    DELETE r
    RETURN count(r) AS deleted
    """

    async with neo4j.run(
        query, username=username, role_slug=role_slug
    ) as result:
        records = await result.data()
        if not records or records[0].get('deleted', 0) == 0:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'User {username!r} does not have role {role_slug!r}',
            )


@users_router.post('/{username}/groups', status_code=204)
async def add_to_group(
    username: str,
    group_add: dict[str, str],
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> None:
    """
    Add a user to a group.

    Parameters:
        username (str): Username to add to group.
        group_add (dict): Dictionary with 'group_slug' key.

    Raises:
        fastapi.HTTPException: HTTP 404 if user or group not found.
    """
    group_slug = group_add.get('group_slug')
    if not group_slug:
        raise fastapi.HTTPException(
            status_code=400,
            detail='group_slug is required',
        )

    query = """
    MATCH (u:User {username: $username})
    MATCH (g:Group {slug: $group_slug})
    MERGE (u)-[:MEMBER_OF]->(g)
    RETURN u, g
    """

    async with neo4j.run(
        query, username=username, group_slug=group_slug
    ) as result:
        records = await result.data()
        if not records:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'User {username!r} or group {group_slug!r} not found',
            )


@users_router.delete('/{username}/groups/{group_slug}', status_code=204)
async def remove_from_group(
    username: str,
    group_slug: str,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('user:update')),
    ],
) -> None:
    """
    Remove a user from a group.

    Parameters:
        username (str): Username to remove from group.
        group_slug (str): Slug of group to remove from.

    Raises:
        fastapi.HTTPException: HTTP 404 if relationship doesn't exist.
    """
    query = """
    MATCH (u:User {username: $username})-[r:MEMBER_OF]->
          (g:Group {slug: $group_slug})
    DELETE r
    RETURN count(r) AS deleted
    """

    async with neo4j.run(
        query, username=username, group_slug=group_slug
    ) as result:
        records = await result.data()
        if not records or records[0].get('deleted', 0) == 0:
            raise fastapi.HTTPException(
                status_code=404,
                detail=f'User {username!r} is not a member of group '
                f'{group_slug!r}',
            )
