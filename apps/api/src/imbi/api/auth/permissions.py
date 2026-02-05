"""Permission checking and authorization dependencies."""

import datetime
import logging
import typing

import fastapi
import jwt
import pydantic
from fastapi import security
from imbi_common import models, neo4j, settings
from imbi_common.auth import core

LOGGER = logging.getLogger(__name__)

# OAuth2 scheme for extracting Bearer tokens from Authorization header
oauth2_scheme = security.HTTPBearer(auto_error=False)


class AuthContext(pydantic.BaseModel):
    """Authentication context for the current request."""

    user: models.User
    session_id: str | None = None
    auth_method: typing.Literal['jwt', 'api_key']
    permissions: set[str] = pydantic.Field(default_factory=set)


async def load_user_permissions(email: str) -> set[str]:
    """
    Get permission names granted to a user.

    Collects permissions from the user's direct roles, group-assigned
    roles, and any inherited roles.

    Parameters:
        email (str): Email of user whose permissions will be resolved.

    Returns:
        set[str]: Set of permission names (for example,
            'blueprint:read', 'project:write').
    """
    query = """
    MATCH (u:User {email: $email})
    OPTIONAL MATCH (u)-[:HAS_ROLE]->(role:Role)
    OPTIONAL MATCH (u)-[:MEMBER_OF*]->(group:Group)
    OPTIONAL MATCH (group)-[:ASSIGNED_ROLE]->(group_role:Role)
    WITH u, collect(DISTINCT role) + collect(DISTINCT group_role) AS all_roles
    UNWIND all_roles AS r
    OPTIONAL MATCH (r)-[:INHERITS_FROM*0..]->(parent:Role)
    WITH DISTINCT parent
    OPTIONAL MATCH (parent)-[:GRANTS]->(perm:Permission)
    RETURN collect(DISTINCT perm.name) AS permissions
    """
    async with neo4j.run(query, email=email) as result:
        records = await result.data()
        if not records:
            return set()
        permission_list: list[str] = records[0].get('permissions', [])
        return set(permission_list)


async def authenticate_jwt(
    token: str, auth_settings: settings.Auth
) -> AuthContext:
    """
    Validate a JWT, load the corresponding user and their permissions,
    and return an AuthContext.

    Parameters:
        token (str): JWT access token string.
        auth_settings (settings.Auth): Configuration used to decode
            and validate the token.

    Returns:
        AuthContext: Authentication context containing the resolved
            user, the token's `jti` as `session_id`, `auth_method`
            set to `'jwt'`, and the user's permission set.

    Raises:
        fastapi.HTTPException: On token expiry, invalid token, invalid
            token type, revoked token, missing subject, user not found,
            or inactive user account.
    """
    try:
        # Decode and validate token
        claims = core.verify_token(token, auth_settings)
    except jwt.ExpiredSignatureError as err:
        raise fastapi.HTTPException(
            status_code=401, detail='Token has expired'
        ) from err
    except jwt.InvalidTokenError as err:
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid token'
        ) from err

    # Check token type
    if claims.get('type') != 'access':
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid token type'
        )

    # Check if token is revoked
    jti = claims.get('jti')
    query = """
    MATCH (t:TokenMetadata {jti: $jti})
    RETURN t.revoked AS revoked
    """
    async with neo4j.run(query, jti=jti) as result:
        records = await result.data()
        if records and records[0].get('revoked'):
            raise fastapi.HTTPException(
                status_code=401, detail='Token revoked'
            )

    # Load user
    email = claims.get('sub')
    if not email:
        raise fastapi.HTTPException(
            status_code=401, detail='Token missing subject'
        )

    user_query = """
    MATCH (u:User {email: $email})
    RETURN u
    """
    async with neo4j.run(user_query, email=email) as result:
        records = await result.data()
        if not records:
            raise fastapi.HTTPException(
                status_code=401, detail='User not found'
            )
        user_data = neo4j.convert_neo4j_types(records[0]['u'])
        user = models.User(**user_data)

    # Check if user is active
    if not user.is_active:
        raise fastapi.HTTPException(
            status_code=401, detail='User account is inactive'
        )

    # Load permissions
    permissions = await load_user_permissions(email)

    return AuthContext(
        user=user,
        session_id=jti,
        auth_method='jwt',
        permissions=permissions,
    )


async def authenticate_api_key(
    key: str, auth_settings: settings.Auth
) -> AuthContext:
    """
    Validate an API key, load the corresponding user and their
    permissions, and return an AuthContext (Phase 5).

    API keys have the format: ik_<key_id>_<secret>

    Parameters:
        key (str): Full API key string.
        auth_settings (settings.Auth): Configuration for validation.

    Returns:
        AuthContext: Authentication context with user, key_id as
            session_id, auth_method set to 'api_key', and filtered
            permissions based on key scopes.

    Raises:
        fastapi.HTTPException: On invalid format, revoked key, expired
            key, invalid secret, or inactive user.
    """
    # Parse API key format: ik_<id>_<secret>
    parts = key.split('_', 2)
    if len(parts) != 3 or parts[0] != 'ik':
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid API key format'
        )

    key_id = f'ik_{parts[1]}'
    key_secret = parts[2]

    # Fetch API key from Neo4j
    query = """
    MATCH (k:APIKey {key_id: $key_id})
    OPTIONAL MATCH (k)-[:OWNED_BY]->(u:User)
    RETURN k, u
    """
    async with neo4j.run(query, key_id=key_id) as result:
        records = await result.data()

    if not records:
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid or revoked API key'
        )

    api_key_data = neo4j.convert_neo4j_types(records[0]['k'])
    user_data = neo4j.convert_neo4j_types(records[0]['u'])

    if not user_data:
        raise fastapi.HTTPException(
            status_code=401, detail='API key user not found'
        )

    # Check if key is revoked
    if api_key_data.get('revoked', False):
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid or revoked API key'
        )

    # Check if key is expired
    expires_at = api_key_data.get('expires_at')
    if expires_at and expires_at < datetime.datetime.now(datetime.UTC):
        raise fastapi.HTTPException(status_code=401, detail='API key expired')

    # Verify key secret (hashed)
    if not core.verify_password(key_secret, api_key_data['key_hash']):
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid or revoked API key'
        )

    # Create user model
    user = models.User(**user_data)

    # Check if user is active
    if not user.is_active:
        raise fastapi.HTTPException(
            status_code=401, detail='User account is inactive'
        )

    # Update last_used timestamp
    update_query = """
    MATCH (k:APIKey {key_id: $key_id})
    SET k.last_used = datetime()
    """
    async with neo4j.run(update_query, key_id=key_id) as result:
        await result.consume()

    # Load user permissions
    all_permissions = await load_user_permissions(user.email)

    # Filter by API key scopes (empty scopes = all permissions)
    scopes = api_key_data.get('scopes', [])
    if scopes:
        filtered_permissions = all_permissions.intersection(set(scopes))
    else:
        filtered_permissions = all_permissions

    return AuthContext(
        user=user,
        session_id=key_id,
        auth_method='api_key',
        permissions=filtered_permissions,
    )


async def get_current_user(
    credentials: security.HTTPAuthorizationCredentials
    | None = fastapi.Depends(oauth2_scheme),  # noqa: B008
) -> AuthContext:
    """FastAPI dependency to get the current authenticated user (Phase 5).

    Supports both JWT and API key authentication. API keys are detected
    by the 'ik_' prefix.

    Args:
        credentials: HTTP Bearer credentials from Authorization header

    Returns:
        AuthContext with user and permissions

    Raises:
        fastapi.HTTPException: If authentication fails

    """
    if not credentials:
        raise fastapi.HTTPException(
            status_code=401,
            detail='Missing authentication credentials',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    auth_settings = settings.get_auth_settings()
    token = credentials.credentials

    # Detect API key format (ik_<id>_<secret>)
    if token.startswith('ik_'):
        return await authenticate_api_key(token, auth_settings)
    else:
        return await authenticate_jwt(token, auth_settings)


def require_permission(
    permission: str,
) -> typing.Callable[[AuthContext], typing.Awaitable[AuthContext]]:
    """
    Create a FastAPI dependency that enforces a specific permission.

    The returned dependency validates the current request's AuthContext:
    admin users bypass the check; otherwise the dependency ensures the
    required permission is present and returns the AuthContext when
    allowed.

    Parameters:
        permission (str): Permission name to require (e.g.,
            "blueprint:read").

    Returns:
        Callable[[AuthContext], Awaitable[AuthContext]]: A dependency
            callable that returns the current AuthContext when the user
            has the required permission.

    Raises:
        fastapi.HTTPException: Raised with status code 403 if the
            current user lacks the required permission.
    """

    async def check_permission(
        auth: typing.Annotated[AuthContext, fastapi.Depends(get_current_user)],
    ) -> AuthContext:
        # Admin users automatically have all permissions
        """
        Enforces that the current user possesses the required
        permission; admin users bypass checks.

        Returns:
            AuthContext: The unchanged authentication context when the
                permission is granted.
        """
        if auth.user.is_admin:
            return auth

        if permission not in auth.permissions:
            LOGGER.warning(
                'Permission denied: user=%s permission=%s',
                auth.user.email,
                permission,
            )
            raise fastapi.HTTPException(
                status_code=403,
                detail=f'Permission denied: {permission} required',
            )
        return auth

    return check_permission


async def check_resource_permission(
    email: str, resource_type: str, resource_slug: str, action: str
) -> bool:
    """
    Determine whether the given user is allowed to perform the
    specified action on the named resource.

    Parameters:
        email (str): Email of the user to check.
        resource_type (str): Resource label to match (e.g.,
            'Blueprint', 'Project').
        resource_slug (str): Slug identifier of the target resource.
        action (str): Action to check (e.g., 'read', 'write',
            'delete').

    Returns:
        bool: `True` if the user has the requested action for the
            resource, `False` otherwise.
    """
    query = """
    MATCH (u:User {email: $email})
    OPTIONAL MATCH (u)-[:MEMBER_OF*]->(group:Group)
    WITH u, collect(DISTINCT group) AS groups
    MATCH (resource {slug: $resource_slug})
    WHERE $resource_type IN labels(resource)
    OPTIONAL MATCH (u)-[user_access:CAN_ACCESS]->(resource)
    OPTIONAL MATCH (group)-[group_access:CAN_ACCESS]->(resource)
    WHERE group IN groups
    WITH user_access, group_access
    WHERE user_access IS NOT NULL OR group_access IS NOT NULL
    WITH collect(DISTINCT user_access.actions) +
         collect(DISTINCT group_access.actions) AS all_actions
    UNWIND all_actions AS action_list
    UNWIND action_list AS action_item
    RETURN collect(DISTINCT action_item) AS actions
    """
    async with neo4j.run(
        query,
        email=email,
        resource_type=resource_type,
        resource_slug=resource_slug,
    ) as result:
        records = await result.data()
        if not records:
            return False
        actions: list[str] = records[0].get('actions', [])
        return action in actions


def require_resource_access(
    resource_type: str, action: str
) -> typing.Callable[[str, AuthContext], typing.Awaitable[AuthContext]]:
    """
    Create a FastAPI dependency that enforces access for a specific
    resource and action.

    The returned dependency validates that the current user has
    permission to perform the given action on the resource identified
    by its slug; on success it returns the provided AuthContext,
    otherwise it raises an HTTP 403 error.

    Parameters:
        resource_type (str): Resource type name (e.g., 'blueprint',
            'project') used to form global permission names and to
            match resource labels.
        action (str): Action to check (e.g., 'read', 'write',
            'delete').

    Returns:
        Callable: A dependency callable that accepts a resource slug
            and an AuthContext and returns the AuthContext if access
            is granted, or raises HTTPException(403) if denied.
    """

    async def check_access(
        slug: str,
        auth: typing.Annotated[AuthContext, fastapi.Depends(get_current_user)],
    ) -> AuthContext:
        # Admin users automatically have all permissions
        """
        Enforces that the current user has access to the specified
        resource and returns the unchanged AuthContext on success.

        Parameters:
            slug (str): The resource identifier (slug) to check access
                for.
            auth (AuthContext): The authentication context for the
                current request.

        Returns:
            AuthContext: The provided auth context when access is
                granted.

        Raises:
            fastapi.HTTPException: With status 403 if the user is not
                authorized to access the resource.
        """
        if auth.user.is_admin:
            return auth

        # First check global permission
        global_permission = f'{resource_type}:{action}'
        if global_permission in auth.permissions:
            return auth

        # Check resource-level permission
        # Convert snake_case to PascalCase for Neo4j labels
        label = ''.join(word.capitalize() for word in resource_type.split('_'))
        has_access = await check_resource_permission(
            auth.user.email, label, slug, action
        )
        if has_access:
            return auth

        LOGGER.warning(
            'Resource access denied: user=%s resource=%s:%s action=%s',
            auth.user.email,
            resource_type,
            slug,
            action,
        )
        raise fastapi.HTTPException(
            status_code=403,
            detail=f'Access denied to {resource_type}:{slug}',
        )

    return check_access
