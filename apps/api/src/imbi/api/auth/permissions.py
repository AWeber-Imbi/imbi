"""Permission checking and authorization dependencies.

Token verification, principal loading, and global permission checks
live in :mod:`imbi.common.auth.permissions`, shared with imbi-assistant
and imbi-scheduler. They are re-exported here so every endpoint in this
service keeps importing them from one place.

What remains local is resource-level authorization: the ``CAN_ACCESS``
edges and the ``resource_type`` -> AGE label map only mean something for
imbi-api's domain entities.
"""

import collections.abc
import logging
import typing

import fastapi

from imbi.api import settings
from imbi.common import graph
from imbi.common.auth import permissions as _shared

__all__ = [
    'ACCESS_COOKIE_NAME',
    'AuthContext',
    'IdentityInfo',
    'PrincipalLabel',
    'PrincipalMatchProp',
    'authenticate_api_key',
    'authenticate_jwt',
    'check_resource_permission',
    'clear_api_key_cache',
    'get_current_user',
    'get_current_user_cookie_fallback',
    'load_all_permission_names',
    'load_principal_permissions',
    'oauth2_scheme',
    'require_permission',
    'require_resource_access',
    'validate_scopes',
]

LOGGER = logging.getLogger(__name__)

ACCESS_COOKIE_NAME = _shared.ACCESS_COOKIE_NAME
AuthContext = _shared.AuthContext
IdentityInfo = _shared.IdentityInfo
PrincipalLabel = _shared.PrincipalLabel
PrincipalMatchProp = _shared.PrincipalMatchProp
authenticate_api_key = _shared.authenticate_api_key
authenticate_jwt = _shared.authenticate_jwt
clear_api_key_cache = _shared.clear_api_key_cache
get_current_user = _shared.get_current_user
get_current_user_cookie_fallback = _shared.get_current_user_cookie_fallback
load_all_permission_names = _shared.load_all_permission_names
load_principal_permissions = _shared.load_principal_permissions
oauth2_scheme = _shared.oauth2_scheme
require_permission = _shared.require_permission
validate_scopes = _shared.validate_scopes

# This service extends ``Auth`` with password policy, MFA, and OAuth
# settings and keeps its own singleton. Point the shared auth path at it
# through a lambda rather than the function object, so a test patching
# ``imbi.api.settings.get_auth_settings`` still governs authentication.
_shared.set_auth_settings_provider(lambda: settings.get_auth_settings())


# Explicit map from a permission ``resource_type`` (the snake-case
# slug used in permission strings like ``project:read``) to the AGE
# vertex label that identifies the node in the graph. Kept explicit
# rather than derived from ``''.join(w.capitalize() ...)`` because
# the naive conversion would map e.g. ``project_logs`` → ``ProjectLogs``
# even though no such label exists, silently denying every request
# instead of surfacing a configuration bug.
_RESOURCE_LABEL_MAP: dict[str, str] = {
    'blueprint': 'Blueprint',
    'document': 'Document',
    'document_template': 'DocumentTemplate',
    'environment': 'Environment',
    'identity_connection': 'IdentityConnection',
    'integration': 'Integration',
    'link_definition': 'LinkDefinition',
    'organization': 'Organization',
    'project': 'Project',
    'project_type': 'ProjectType',
    'release': 'Release',
    'role': 'Role',
    'tag': 'Tag',
    'team': 'Team',
}


def _resolve_resource_label(resource_type: str) -> str:
    """Return the AGE label for a permission resource type.

    Raises ``KeyError`` so a missing mapping shows up as a 500 on the
    affected endpoint instead of a silent 403 — the latter would be a
    classic "works on the dev's box, denied in prod" footgun.
    """
    try:
        return _RESOURCE_LABEL_MAP[resource_type]
    except KeyError as exc:
        raise KeyError(
            f'Unknown resource_type {resource_type!r}: add it to'
            ' _RESOURCE_LABEL_MAP'
        ) from exc


async def check_resource_permission(
    db: graph.Graph,
    email: str,
    resource_type: str,
    resource_slug: str,
    action: str,
) -> bool:
    """
    Determine whether the given user is allowed to perform the
    specified action on the named resource.

    Parameters:
        db: Graph database connection.
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
    query = (
        'MATCH (u:User {{email: {email}}}) '
        'MATCH (resource {{slug: {resource_slug}}}) '
        'WHERE {resource_type} IN labels(resource) '
        'MATCH (u)-[access:CAN_ACCESS]->(resource) '
        'RETURN {action} IN access.actions'
    )
    records = await db.execute(
        query,
        {
            'email': email,
            'resource_type': resource_type,
            'resource_slug': resource_slug,
            'action': action,
        },
        columns=['allowed'],
    )
    if not records:
        return False
    return bool(graph.parse_agtype(records[0].get('allowed')))


def require_resource_access(
    resource_type: str, action: str
) -> typing.Callable[..., collections.abc.Awaitable[AuthContext]]:
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
        db: graph.Pool,
    ) -> AuthContext:
        """Enforce access to a specific resource.

        Parameters:
            slug: The resource identifier to check.
            auth: The authentication context.
            db: Graph database connection (injected by FastAPI).

        Returns:
            AuthContext when access is granted.

        """
        if auth.is_admin:
            return auth

        # First check global permission
        global_permission = f'{resource_type}:{action}'
        if global_permission in auth.permissions:
            return auth

        # Check resource-level permission (users only)
        if auth.user:
            label = _resolve_resource_label(resource_type)
            has_access = await check_resource_permission(
                db, auth.user.email, label, slug, action
            )
            if has_access:
                return auth

        LOGGER.warning(
            'Resource access denied: principal=%s resource=%s:%s action=%s',
            auth.principal_name,
            resource_type,
            slug,
            action,
        )
        raise fastapi.HTTPException(
            status_code=403,
            detail=f'Access denied to {resource_type}:{slug}',
        )

    return check_access
