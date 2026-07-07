"""Permission checking and authorization dependencies."""

import asyncio
import collections
import collections.abc
import datetime
import hashlib
import logging
import time
import typing

import fastapi
import jwt
import pydantic
from fastapi import security
from imbi_common import access_log, graph
from imbi_common.auth import core

from imbi_api import models, settings
from imbi_api.auth import password

LOGGER = logging.getLogger(__name__)

# OAuth2 scheme for extracting Bearer tokens from Authorization header
oauth2_scheme = security.HTTPBearer(auto_error=False)

# Name of the cookie that mirrors the access token. The SPA authenticates
# with a Bearer header on fetch/XHR; this cookie exists solely so browser
# subresource requests (``<img src>`` to the upload-serving endpoints),
# which cannot set an Authorization header, still carry credentials. It is
# set by the auth endpoints and honored only by the cookie-fallback
# dependency below.
ACCESS_COOKIE_NAME = 'imbi_access_token'


class IdentityInfo(pydantic.BaseModel):
    """A single third-party identity connection for an authenticated user."""

    plugin_slug: str
    subject: str


class AuthContext(pydantic.BaseModel):
    """Authentication context for the current request."""

    user: models.User | None = None
    service_account: models.ServiceAccount | None = None
    session_id: str | None = None
    auth_method: typing.Literal['jwt', 'api_key', 'client_credentials']
    permissions: set[str] = pydantic.Field(default_factory=set)
    identities: list[IdentityInfo] = pydantic.Field(default_factory=list)

    def identity_for(self, plugin_slug: str) -> str | None:
        """Return the subject for the given plugin_slug, or None."""
        for i in self.identities:
            if i.plugin_slug == plugin_slug:
                return i.subject
        return None

    @property
    def principal_name(self) -> str:
        """Return the name of the authenticated principal."""
        if self.user:
            return self.user.email
        if self.service_account:
            return self.service_account.slug
        return 'unknown'

    @property
    def is_admin(self) -> bool:
        """Return whether the principal is an admin."""
        return self.user.is_admin if self.user else False

    @property
    def require_user(self) -> models.User:
        """Return the authenticated user, raising 403 if absent.

        Use this in endpoints that require a human user (not a
        service account).
        """
        if self.user is None:
            raise fastapi.HTTPException(
                403, 'This endpoint requires user authentication'
            )
        return self.user


# M15: bounded per-process cache for successful API-key auth so a
# hot path (CI bot hammering the API with the same key) doesn't pay
# the full Argon2 verify + graph round-trip on every request. The
# cache value is a fully-formed AuthContext; the key is the SHA-256
# of the raw API key string so we don't keep the plaintext key in
# memory. TTL is short so revocations / scope changes propagate
# within a minute.
_API_KEY_CACHE_TTL_SECONDS = 60
_API_KEY_CACHE_MAX_ENTRIES = 1024
_api_key_cache: collections.OrderedDict[str, tuple[float, AuthContext]] = (
    collections.OrderedDict()
)


def _api_key_cache_key(key: str) -> str:
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def _api_key_cache_lookup(key: str) -> AuthContext | None:
    """Return a cached AuthContext if present and unexpired."""
    h = _api_key_cache_key(key)
    entry = _api_key_cache.get(h)
    if entry is None:
        return None
    expires, ctx = entry
    if time.monotonic() > expires:
        _api_key_cache.pop(h, None)
        return None
    # Refresh LRU recency on hit.
    _api_key_cache.move_to_end(h)
    return ctx


def _api_key_cache_store(key: str, ctx: AuthContext) -> None:
    """Store an AuthContext in the bounded LRU cache."""
    h = _api_key_cache_key(key)
    while len(_api_key_cache) >= _API_KEY_CACHE_MAX_ENTRIES:
        _api_key_cache.popitem(last=False)
    _api_key_cache[h] = (
        time.monotonic() + _API_KEY_CACHE_TTL_SECONDS,
        ctx,
    )


def clear_api_key_cache() -> None:
    """Drop every cached API-key AuthContext.

    Tests use this to keep cases independent; callers that rotate /
    revoke a key in-process can also use it for instant invalidation
    instead of waiting on the TTL.
    """
    _api_key_cache.clear()


PrincipalLabel = typing.Literal['User', 'ServiceAccount']
PrincipalMatchProp = typing.Literal['email', 'slug']

_ALLOWED_PRINCIPAL_SELECTORS: frozenset[
    tuple[PrincipalLabel, PrincipalMatchProp]
] = frozenset(
    {
        ('User', 'email'),
        ('ServiceAccount', 'slug'),
    }
)


async def load_all_permission_names(db: graph.Graph) -> set[str]:
    """Return the set of seeded ``Permission.name`` values.

    Used to validate API-key / SA-key / client-credential scope lists
    at creation time — a scope that doesn't correspond to a seeded
    permission would silently grant nothing (the auth path
    intersects scopes with the principal's actual permissions), but
    persisting bogus scopes pollutes the audit trail and hides
    typos.
    """
    records = await db.execute(
        'MATCH (p:Permission) RETURN p.name AS name',
        {},
        columns=['name'],
    )
    names: set[str] = set()
    for row in records:
        raw = graph.parse_agtype(row.get('name'))
        if isinstance(raw, str) and raw:
            names.add(raw)
    return names


async def validate_scopes(
    db: graph.Graph, scopes: collections.abc.Iterable[str]
) -> None:
    """Raise ``HTTPException(400)`` if any scope isn't a seeded Permission.

    An empty / all-scopes list (``[]``) is treated as "no restriction"
    by callers and passes validation trivially.
    """
    requested = {s for s in scopes if s}
    if not requested:
        return
    known = await load_all_permission_names(db)
    unknown = sorted(requested - known)
    if unknown:
        raise fastapi.HTTPException(
            status_code=400,
            detail=(
                'Unknown scope(s): '
                + ', '.join(unknown)
                + '. Scopes must match seeded Permission names.'
            ),
        )


async def load_principal_permissions(
    db: graph.Graph,
    label: PrincipalLabel,
    match_prop: PrincipalMatchProp,
    value: str,
) -> set[str]:
    """Get permission names granted to a principal (user or SA).

    Collects permissions from the principal's organization memberships,
    following role inheritance via ``INHERITS_FROM`` and ``GRANTS``
    relationships.

    Parameters:
        db: Graph database connection.
        label: Node label of the principal (``'User'`` or
            ``'ServiceAccount'``).
        match_prop: Property name on the principal used to match
            (``'email'`` for users, ``'slug'`` for service accounts).
        value: Value of ``match_prop`` identifying the principal.

    Returns:
        Set of permission names (for example, ``'blueprint:read'``).

    Raises:
        ValueError: If ``(label, match_prop)`` is not an allowed
            principal selector. ``label`` and ``match_prop`` are
            interpolated into the Cypher template, so this guard
            prevents Cypher injection via future non-constant inputs.
    """
    if (label, match_prop) not in _ALLOWED_PRINCIPAL_SELECTORS:
        raise ValueError(
            f'Unsupported principal selector: ({label!r}, {match_prop!r})'
        )
    # Apache AGE does not honor the zero-hop case in variable-length
    # paths (``*0..``), so the start role itself would be excluded
    # from the traversal. Collect ancestors with ``*1..`` then union
    # the start role back in.
    query = (
        f'MATCH (p:{label} {{{{{match_prop}: {{value}}}}}})'
        '-[m:MEMBER_OF]->(o:Organization) '
        'MATCH (r:Role {{slug: m.role}}) '
        'OPTIONAL MATCH (r)-[:INHERITS_FROM*1..]->(ancestor:Role) '
        'WITH r, collect(DISTINCT ancestor) AS ancestors '
        'UNWIND ancestors + [r] AS role '
        'WITH DISTINCT role '
        'OPTIONAL MATCH (role)-[:GRANTS]->(perm:Permission) '
        'RETURN collect(DISTINCT perm.name)'
    )
    records = await db.execute(
        query, {'value': value}, columns=['permissions']
    )
    if not records:
        return set()
    raw: typing.Any = graph.parse_agtype(records[0].get('permissions'))
    if isinstance(raw, list):
        return {
            item
            for item in typing.cast(list[str | typing.Any], raw)
            if isinstance(item, str)
        }
    return set()


async def _load_user_identities(
    db: graph.Graph,
    user_id: str,
) -> list[IdentityInfo]:
    """Return active third-party identity connections for the user.

    Identity enrichment is auxiliary — authentication has already
    succeeded by the time this runs.  A failure here (DB hiccup,
    AGType parse error) must not turn a valid token into a 5xx, so
    all exceptions are caught, logged, and treated as "no identities".
    """
    query: typing.LiteralString = """
    MATCH (u:User {{id: {user_id}}})-[:HAS_IDENTITY]->(c:IdentityConnection)
    WHERE c.status = 'active'
    OPTIONAL MATCH (i:Integration) WHERE i.id = c.integration_id
    RETURN i.plugin AS plugin_slug, c.subject AS subject
    """
    try:
        records = await db.execute(
            query,
            {'user_id': user_id},
            ['plugin_slug', 'subject'],
        )
        result: list[IdentityInfo] = []
        for row in records:
            plugin_slug = graph.parse_agtype(row['plugin_slug'])
            subject = graph.parse_agtype(row['subject'])
            if plugin_slug and subject:
                result.append(
                    IdentityInfo(plugin_slug=plugin_slug, subject=subject)
                )
        return result
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to load identity connections for user_id=%s',
            user_id,
            exc_info=True,
        )
        return []


async def authenticate_jwt(
    db: graph.Graph,
    token: str,
    auth_settings: settings.Auth,
) -> AuthContext:
    """
    Validate a JWT, load the corresponding user and their permissions,
    and return an AuthContext.

    Parameters:
        db: Graph database connection.
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
    query = 'MATCH (t:TokenMetadata {{jti: {jti}}}) RETURN t.revoked'
    records = await db.execute(query, {'jti': jti}, columns=['revoked'])
    if records:
        revoked = graph.parse_agtype(records[0].get('revoked'))
        if revoked:
            raise fastapi.HTTPException(
                status_code=401, detail='Token revoked'
            )

    # Load principal (user or service account)
    subject = claims.get('sub')
    if not subject:
        raise fastapi.HTTPException(
            status_code=401, detail='Token missing subject'
        )

    auth_method = claims.get('auth_method', 'jwt')

    if auth_method == 'client_credentials':
        # Service account token
        sa_results = await db.match(models.ServiceAccount, {'slug': subject})
        if not sa_results:
            raise fastapi.HTTPException(
                status_code=401,
                detail='Service account not found',
            )
        sa = sa_results[0]

        if not sa.is_active:
            raise fastapi.HTTPException(
                status_code=401,
                detail='Service account is inactive',
            )

        perms = await load_principal_permissions(
            db, 'ServiceAccount', 'slug', subject
        )
        return AuthContext(
            service_account=sa,
            session_id=jti,
            auth_method='client_credentials',
            permissions=perms,
        )

    # Standard user token
    user_results = await db.match(models.User, {'email': subject})
    if not user_results:
        raise fastapi.HTTPException(status_code=401, detail='User not found')
    user = user_results[0]

    # Check if user is active
    if not user.is_active:
        raise fastapi.HTTPException(
            status_code=401, detail='User account is inactive'
        )

    # Load permissions
    perms = await load_principal_permissions(db, 'User', 'email', subject)
    identities = await _load_user_identities(db, user.id)

    return AuthContext(
        user=user,
        session_id=jti,
        auth_method='jwt',
        permissions=perms,
        identities=identities,
    )


async def _stamp_api_key_last_used(
    db: graph.Graph,
    key_id: str,
    auth_settings: settings.Auth,
) -> None:
    """Set last_used on the APIKey node identified by key_id.

    Skips the write atomically when the existing ``last_used`` is
    newer than ``auth_settings.last_used_throttle_seconds`` ago. The
    value only needs to be accurate to the nearest minute or so; we
    don't need to spend a graph write on every authenticated
    request. A throttle of ``0`` disables this and always writes.

    AGE's cypher() wrapper requires a RETURN clause to properly
    finalize a write operation — omitting it causes an internal
    "Entity failed to be updated" error. Failures are logged and
    swallowed: the stamp is best-effort and must not fail authentication.
    """
    now = datetime.datetime.now(datetime.UTC)
    threshold = now - datetime.timedelta(
        seconds=max(0, auth_settings.last_used_throttle_seconds)
    )
    query: typing.LiteralString = (
        'MATCH (k:APIKey {{key_id: {key_id}}})'
        ' WHERE k.last_used IS NULL OR k.last_used < {threshold}'
        ' SET k.last_used = {now} RETURN k'
    )
    try:
        await db.execute(
            query,
            {
                'key_id': key_id,
                'now': now.isoformat(),
                'threshold': threshold.isoformat(),
            },
            columns=['k'],
        )
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'Failed to stamp last_used for API key %s',
            key_id,
            exc_info=True,
        )


async def authenticate_api_key(
    db: graph.Graph,
    key: str,
    auth_settings: settings.Auth,
) -> AuthContext:
    """
    Validate an API key, load the corresponding user and their
    permissions, and return an AuthContext (Phase 5).

    API keys have the format: ik_<key_id>_<secret>

    Parameters:
        db: Graph database connection.
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

    # M15: fast path — a hot key (e.g. a CI bot looping requests)
    # would otherwise re-run Argon2 + 2 graph round-trips per call.
    # The cache short-circuits the whole thing for up to
    # ``_API_KEY_CACHE_TTL_SECONDS``; revocations propagate at the
    # next miss. ``_stamp_api_key_last_used`` is still invoked on a
    # miss, so ``last_used`` updates at most once per TTL window.
    cached = _api_key_cache_lookup(key)
    if cached is not None:
        return cached

    # Fetch API key and owner (User or ServiceAccount)
    query = (
        'MATCH (k:APIKey {{key_id: {key_id}}}) '
        'OPTIONAL MATCH (k)-[:OWNED_BY]->(u:User) '
        'OPTIONAL MATCH (k)-[:OWNED_BY]->(s:ServiceAccount) '
        'RETURN k, u, s'
    )
    records = await db.execute(
        query, {'key_id': key_id}, columns=['k', 'u', 's']
    )

    if not records:
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid or revoked API key'
        )

    api_key_data = graph.parse_agtype(records[0]['k'])
    user_data = graph.parse_agtype(records[0]['u'])
    sa_data = graph.parse_agtype(records[0]['s'])

    if not user_data and not sa_data:
        raise fastapi.HTTPException(
            status_code=401, detail='API key owner not found'
        )

    # Check if key is revoked
    if api_key_data.get('revoked', False):
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid or revoked API key'
        )

    # Check if key is expired -- AGE stores datetime as ISO strings
    expires_at = api_key_data.get('expires_at')
    if expires_at:
        if isinstance(expires_at, str):
            expires_at = datetime.datetime.fromisoformat(
                expires_at,
            )
        if expires_at < datetime.datetime.now(datetime.UTC):
            raise fastapi.HTTPException(
                status_code=401,
                detail='API key expired',
            )

    # Verify key secret (hashed)
    if not await asyncio.to_thread(
        password.verify_password, key_secret, api_key_data['key_hash']
    ):
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid or revoked API key'
        )

    # Resolve owner and permissions
    scopes = models.parse_scopes(
        api_key_data.get('scopes', []),
    )

    if sa_data:
        sa = models.ServiceAccount(**sa_data)
        if not sa.is_active:
            raise fastapi.HTTPException(
                status_code=401,
                detail='Service account is inactive',
            )
        all_perms = await load_principal_permissions(
            db, 'ServiceAccount', 'slug', sa.slug
        )
        filtered = all_perms.intersection(set(scopes)) if scopes else all_perms

        # Update last_used only after all validation passes
        await _stamp_api_key_last_used(db, key_id, auth_settings)

        ctx = AuthContext(
            service_account=sa,
            session_id=key_id,
            auth_method='api_key',
            permissions=filtered,
        )
        _api_key_cache_store(key, ctx)
        return ctx

    user = models.User(**user_data)
    if not user.is_active:
        raise fastapi.HTTPException(
            status_code=401, detail='User account is inactive'
        )

    all_perms = await load_principal_permissions(
        db, 'User', 'email', user.email
    )
    filtered = all_perms.intersection(set(scopes)) if scopes else all_perms
    identities = await _load_user_identities(db, user.id)

    # Update last_used only after all validation passes
    await _stamp_api_key_last_used(db, key_id, auth_settings)

    ctx = AuthContext(
        user=user,
        session_id=key_id,
        auth_method='api_key',
        permissions=filtered,
        identities=identities,
    )
    _api_key_cache_store(key, ctx)
    return ctx


async def get_current_user(
    db: graph.Pool,
    credentials: security.HTTPAuthorizationCredentials
    | None = fastapi.Depends(oauth2_scheme),  # noqa: B008
) -> AuthContext:
    """FastAPI dependency to get the current authenticated user.

    Supports both JWT and API key authentication. API keys are
    detected by the 'ik_' prefix.

    Args:
        db: Graph database connection (injected by FastAPI).
        credentials: HTTP Bearer credentials from Authorization
            header.

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
    return await _authenticate_token(
        db, credentials.credentials, settings.get_auth_settings()
    )


async def _authenticate_token(
    db: graph.Graph,
    token: str,
    auth_settings: settings.Auth,
) -> AuthContext:
    """Resolve an AuthContext from a raw bearer token.

    Detects the API key format (``ik_<id>_<secret>``) and otherwise
    treats the token as a JWT.
    """
    if token.startswith('ik_'):
        ctx = await authenticate_api_key(db, token, auth_settings)
        # Cache the key's owner so imbi-common's access log renders the
        # person (email / service-account slug) instead of the opaque
        # ``ik_<id>`` it parses from the Authorization header.
        access_log.remember_api_key_principal(
            ctx.session_id or '', ctx.principal_name
        )
        return ctx
    return await authenticate_jwt(db, token, auth_settings)


async def get_current_user_cookie_fallback(
    db: graph.Pool,
    request: fastapi.Request,
    credentials: security.HTTPAuthorizationCredentials
    | None = fastapi.Depends(oauth2_scheme),  # noqa: B008
) -> AuthContext:
    """Like ``get_current_user`` but also accepts the access cookie.

    Browser subresource requests (e.g. ``<img src>``) cannot set an
    ``Authorization`` header, so for the upload-serving GET endpoints the
    access token is also read from the :data:`ACCESS_COOKIE_NAME` cookie
    when the header is absent. The Bearer header still takes precedence.

    Raises:
        fastapi.HTTPException: If neither a header nor cookie token is
            present.

    """
    token = (
        credentials.credentials
        if credentials
        else request.cookies.get(ACCESS_COOKIE_NAME)
    )
    if not token:
        raise fastapi.HTTPException(
            status_code=401,
            detail='Missing authentication credentials',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    return await _authenticate_token(db, token, settings.get_auth_settings())


def require_permission(
    permission: str,
    *,
    allow_cookie: bool = False,
) -> typing.Callable[[AuthContext], collections.abc.Awaitable[AuthContext]]:
    """
    Create a FastAPI dependency that enforces a specific permission.

    The returned dependency validates the current request's AuthContext:
    admin users bypass the check; otherwise the dependency ensures the
    required permission is present and returns the AuthContext when
    allowed.

    Parameters:
        permission (str): Permission name to require (e.g.,
            "blueprint:read").
        allow_cookie (bool): When True, the access token may also be
            supplied via the :data:`ACCESS_COOKIE_NAME` cookie instead of
            the Authorization header. Intended only for endpoints loaded
            as browser subresources (``<img src>``), which cannot send a
            Bearer header.

    Returns:
        Callable[[AuthContext], Awaitable[AuthContext]]: A dependency
            callable that returns the current AuthContext when the user
            has the required permission.

    Raises:
        fastapi.HTTPException: Raised with status code 403 if the
            current user lacks the required permission.
    """
    resolver = (
        get_current_user_cookie_fallback if allow_cookie else get_current_user
    )

    async def check_permission(
        auth: typing.Annotated[AuthContext, fastapi.Depends(resolver)],
    ) -> AuthContext:
        """Enforce that the principal has the required permission.

        Admin users bypass checks. Service accounts never bypass.

        Returns:
            AuthContext when the permission is granted.

        """
        if auth.is_admin:
            return auth

        if permission not in auth.permissions:
            LOGGER.warning(
                'Permission denied: principal=%s permission=%s',
                auth.principal_name,
                permission,
            )
            raise fastapi.HTTPException(
                status_code=403,
                detail=f'Permission denied: {permission} required',
            )
        return auth

    return check_permission


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
