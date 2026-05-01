"""Admin endpoints for login auth provider configuration.

These endpoints expose the subset of ``ServiceApplication`` rows that
are flagged for use as login providers (``usage`` in ``'login'`` /
``'both'``). Cross-org by design: auth providers are an instance-level
concern even though each row is owned by a single organization.
"""

from __future__ import annotations

import json
import logging
import typing

import fastapi
import psycopg
import pydantic
from imbi_common import graph
from imbi_common.auth import encryption

from imbi_api import settings
from imbi_api.auth import login_providers, permissions
from imbi_api.domain import models
from imbi_api.graph_sql import props_template, set_clause

LOGGER = logging.getLogger(__name__)

auth_providers_router = fastapi.APIRouter(
    prefix='/admin/auth-providers',
    tags=['Admin', 'Auth Providers'],
)


_OAuthAppType = typing.Literal['google', 'github', 'oidc']
_LoginUsage = typing.Literal['login', 'both']


def _parse_json_field(value: typing.Any, default: typing.Any) -> typing.Any:
    """Decode a graph-stored JSON string field, defaulting on errors."""
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return value


def _row_to_response(
    app: dict[str, typing.Any],
    svc: dict[str, typing.Any] | None,
    org: dict[str, typing.Any] | None,
) -> dict[str, typing.Any]:
    """Build a serializable response dict from raw graph data."""
    return {
        'slug': app['slug'],
        'name': app.get('name', app['slug']),
        'usage': app.get('usage', 'integration'),
        'oauth_app_type': app.get('oauth_app_type'),
        'client_id': app.get('client_id'),
        'issuer_url': app.get('issuer_url'),
        'allowed_domains': _parse_json_field(app.get('allowed_domains'), []),
        'scopes': _parse_json_field(app.get('scopes'), []),
        'status': app.get('status', 'active'),
        'description': app.get('description'),
        'callback_url': settings.oauth_callback_url(app['slug']),
        'has_secret': bool(app.get('client_secret')),
        'authorization_endpoint': (
            svc.get('authorization_endpoint') if svc else None
        ),
        'token_endpoint': svc.get('token_endpoint') if svc else None,
        'revoke_endpoint': svc.get('revoke_endpoint') if svc else None,
        'third_party_service_slug': svc.get('slug') if svc else None,
        'third_party_service_name': svc.get('name') if svc else None,
        'organization_slug': org.get('slug') if org else None,
        'organization_name': org.get('name') if org else None,
    }


class AuthProviderResponse(pydantic.BaseModel):
    """Response model for an auth provider row."""

    model_config = pydantic.ConfigDict(extra='allow')

    slug: str
    name: str
    usage: typing.Literal['login', 'integration', 'both']
    oauth_app_type: _OAuthAppType | None = None
    client_id: str | None = None
    issuer_url: str | None = None
    allowed_domains: list[str] = []
    scopes: list[str] = []
    status: str = 'active'
    description: str | None = None
    callback_url: str = ''
    has_secret: bool = False
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    revoke_endpoint: str | None = None
    third_party_service_slug: str | None = None
    third_party_service_name: str | None = None
    organization_slug: str | None = None
    organization_name: str | None = None


_OAUTH_APP_TYPE_LABELS: dict[_OAuthAppType, str] = {
    'google': 'Google',
    'github': 'GitHub',
    'oidc': 'OIDC',
}

_DEFAULT_AUTH_ORG_SLUG = 'default'


def _default_service_slug(oauth_app_type: _OAuthAppType) -> str:
    return f'auth-{oauth_app_type}'


class AuthProviderCreate(pydantic.BaseModel):
    """Request body for ``POST /admin/auth-providers``.

    The UI surfaces only the OAuth-shaped fields; the parent
    ``Organization`` / ``ThirdPartyService`` and the row's ``slug``
    /``name`` are derived from ``oauth_app_type`` when omitted. The
    parent nodes are MERGEd so first-time configuration auto-creates
    the synthetic plumbing.
    """

    oauth_app_type: _OAuthAppType
    client_id: str = pydantic.Field(min_length=1)
    client_secret: str = pydantic.Field(min_length=1)
    issuer_url: str | None = None
    allowed_domains: list[str] = pydantic.Field(default_factory=list)
    scopes: list[str] = pydantic.Field(default_factory=list)
    usage: _LoginUsage = 'login'
    description: str | None = None
    # Optional overrides — if omitted, derived from ``oauth_app_type``.
    slug: str | None = pydantic.Field(
        default=None,
        pattern=r'^[a-z][a-z0-9-]*$',
        min_length=2,
        max_length=64,
    )
    name: str | None = pydantic.Field(
        default=None, min_length=1, max_length=128
    )
    org_slug: str | None = pydantic.Field(default=None, min_length=1)
    third_party_service_slug: str | None = pydantic.Field(
        default=None, min_length=1
    )

    @pydantic.model_validator(mode='after')
    def _validate(self) -> typing.Self:
        models.validate_login_app_fields(
            self.usage,
            self.oauth_app_type,
            self.client_id,
            self.issuer_url,
            self.allowed_domains,
        )
        return self

    @property
    def resolved_slug(self) -> str:
        return self.slug or self.oauth_app_type

    @property
    def resolved_name(self) -> str:
        return self.name or _OAUTH_APP_TYPE_LABELS[self.oauth_app_type]

    @property
    def resolved_org_slug(self) -> str:
        return self.org_slug or _DEFAULT_AUTH_ORG_SLUG

    @property
    def resolved_service_slug(self) -> str:
        return self.third_party_service_slug or _default_service_slug(
            self.oauth_app_type
        )


class AuthProviderUpdate(pydantic.BaseModel):
    """Request body for ``PUT /admin/auth-providers/{slug}``."""

    name: str = pydantic.Field(min_length=1, max_length=128)
    description: str | None = None
    oauth_app_type: _OAuthAppType
    client_id: str = pydantic.Field(min_length=1)
    client_secret: str | None = None
    issuer_url: str | None = None
    allowed_domains: list[str] = pydantic.Field(default_factory=list)
    scopes: list[str] = pydantic.Field(default_factory=list)
    usage: _LoginUsage = 'login'

    @pydantic.model_validator(mode='after')
    def _validate(self) -> typing.Self:
        models.validate_login_app_fields(
            self.usage,
            self.oauth_app_type,
            self.client_id,
            self.issuer_url,
            self.allowed_domains,
        )
        return self


_LIST_QUERY: typing.LiteralString = """
MATCH (a:ServiceApplication)-[:REGISTERED_IN]->(s:ThirdPartyService)
      -[:BELONGS_TO]->(o:Organization)
WHERE a.usage IN ['login', 'both']
RETURN a{{.*}} AS app, s{{.*}} AS service, o{{.*}} AS organization
ORDER BY a.slug
"""


_GET_QUERY: typing.LiteralString = """
MATCH (a:ServiceApplication {{slug: {slug}}})
      -[:REGISTERED_IN]->(s:ThirdPartyService)
      -[:BELONGS_TO]->(o:Organization)
RETURN a{{.*}} AS app, s{{.*}} AS service, o{{.*}} AS organization
"""


@auth_providers_router.get('', response_model=list[AuthProviderResponse])
async def list_auth_providers(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('auth_providers:read')),
    ],
) -> list[AuthProviderResponse]:
    """List every login-eligible service application across orgs."""
    records = await db.execute(
        _LIST_QUERY, {}, ['app', 'service', 'organization']
    )
    out: list[AuthProviderResponse] = []
    for record in records:
        app = graph.parse_agtype(record['app'])
        svc = graph.parse_agtype(record.get('service'))
        org = graph.parse_agtype(record.get('organization'))
        out.append(AuthProviderResponse(**_row_to_response(app, svc, org)))
    return out


@auth_providers_router.get('/{slug}', response_model=AuthProviderResponse)
async def get_auth_provider(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('auth_providers:read')),
    ],
) -> AuthProviderResponse:
    """Fetch a single login-eligible service application by slug."""
    records = await db.execute(
        _GET_QUERY, {'slug': slug}, ['app', 'service', 'organization']
    )
    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Auth provider {slug!r} not found',
        )
    app = graph.parse_agtype(records[0]['app'])
    if app.get('usage') not in ('login', 'both'):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Auth provider {slug!r} not found',
        )
    svc = graph.parse_agtype(records[0].get('service'))
    org = graph.parse_agtype(records[0].get('organization'))
    return AuthProviderResponse(**_row_to_response(app, svc, org))


_FETCH_BY_SLUG: typing.LiteralString = """
MATCH (a:ServiceApplication {{slug: {slug}}})
      -[:REGISTERED_IN]->(s:ThirdPartyService)
      -[:BELONGS_TO]->(o:Organization)
RETURN a{{.*}} AS app, s{{.*}} AS service, o{{.*}} AS organization
"""


@auth_providers_router.post(
    '', status_code=201, response_model=AuthProviderResponse
)
async def create_auth_provider(
    data: AuthProviderCreate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('auth_providers:write')
        ),
    ],
) -> AuthProviderResponse:
    """Create or promote a service application as a login provider.

    If a row with ``slug`` already exists in the targeted service, its
    ``usage``/``oauth_app_type``/etc. are updated to match this body
    (effectively promoting it from ``'integration'`` to ``'login'`` /
    ``'both'``). Otherwise a new ``ServiceApplication`` is created and
    linked to the parent ``ThirdPartyService``.
    """
    encryptor = encryption.TokenEncryption.get_instance()
    encrypted_secret = encryptor.encrypt(data.client_secret)

    resolved_slug = data.resolved_slug
    resolved_name = data.resolved_name
    resolved_org_slug = data.resolved_org_slug
    resolved_service_slug = data.resolved_service_slug

    # Look up existing row first (across the targeted service).
    existing_records = await db.execute(
        _FETCH_BY_SLUG,
        {'slug': resolved_slug},
        ['app', 'service', 'organization'],
    )
    if existing_records:
        # Reject collisions whose parent service/org doesn't match the
        # request: silently rewriting another service's provider would
        # both mis-attribute the response and let one tenant clobber
        # another's OAuth credentials. Only enforce when the caller
        # explicitly pinned a parent — otherwise treat the existing
        # row as the implicit target and route through the update
        # branch.
        existing_svc: dict[str, typing.Any] = (
            graph.parse_agtype(existing_records[0].get('service')) or {}
        )
        existing_org: dict[str, typing.Any] = (
            graph.parse_agtype(existing_records[0].get('organization')) or {}
        )
        existing_svc_slug = existing_svc.get('slug')
        existing_org_slug = existing_org.get('slug')
        if (
            data.third_party_service_slug is not None
            and existing_svc_slug != data.third_party_service_slug
        ) or (
            data.org_slug is not None and existing_org_slug != data.org_slug
        ):
            raise fastapi.HTTPException(
                status_code=409,
                detail=(
                    f'Auth provider {resolved_slug!r} already exists under '
                    f'{existing_org_slug!r}/{existing_svc_slug!r}'
                ),
            )
        update_props = {
            'name': resolved_name,
            'description': data.description,
            'usage': data.usage,
            'oauth_app_type': data.oauth_app_type,
            'client_id': data.client_id,
            'client_secret': encrypted_secret,
            'issuer_url': data.issuer_url,
            'allowed_domains': json.dumps(list(data.allowed_domains)),
            'scopes': json.dumps(list(data.scopes)),
        }
        set_stmt = set_clause('a', update_props)
        update_query: str = (
            'MATCH (a:ServiceApplication {{slug: {slug}}})'
            f' {set_stmt}'
            ' RETURN a{{.*}} AS app'
        )
        params = {'slug': resolved_slug, **update_props}
        await db.execute(update_query, params, ['app'])
        login_providers.invalidate_cache(resolved_slug)
        records = await db.execute(
            _FETCH_BY_SLUG,
            {'slug': resolved_slug},
            ['app', 'service', 'organization'],
        )
        app = graph.parse_agtype(records[0]['app'])
        svc = graph.parse_agtype(records[0].get('service'))
        org = graph.parse_agtype(records[0].get('organization'))
        LOGGER.info(
            'Auth provider %s updated by %s',
            resolved_slug,
            auth.principal_name,
        )
        return AuthProviderResponse(**_row_to_response(app, svc, org))

    # New row. MERGE the synthetic parent org + service so first-time
    # configuration auto-creates the plumbing, then CREATE the
    # ServiceApplication under it. The synthetic service vendor matches
    # the OAuth app type so admins viewing the third-party-services
    # screen can recognize it.
    create_props: dict[str, typing.Any] = {
        'slug': resolved_slug,
        'name': resolved_name,
        'description': data.description,
        'app_type': 'oauth',
        'application_url': None,
        'callback_url': None,
        'client_id': data.client_id,
        'client_secret': encrypted_secret,
        'webhook_secret': None,
        'private_key': None,
        'signing_secret': None,
        'scopes': json.dumps(list(data.scopes)),
        'settings': json.dumps({}),
        'status': 'active',
        'usage': data.usage,
        'oauth_app_type': data.oauth_app_type,
        'issuer_url': data.issuer_url,
        'allowed_domains': json.dumps(list(data.allowed_domains)),
    }
    app_tpl = props_template(create_props)

    service_label = (
        f'{_OAUTH_APP_TYPE_LABELS[data.oauth_app_type]} Auth Provider'
    )
    # When the caller didn't pin a specific org, attach the synthetic
    # parent service to whatever organization already exists in the
    # graph rather than minting a new "default" one. The actual choice
    # only matters for the row's data home — visibility on the
    # third-party-services screens is controlled by usage, not the
    # parent org. Pre-flight to fail loudly if no org is present yet.
    if data.org_slug is None:
        org_lookup_query: typing.LiteralString = (
            'MATCH (o:Organization) RETURN o.slug AS slug ORDER BY o.slug'
            ' LIMIT 1'
        )
        org_records = await db.execute(org_lookup_query, {}, ['slug'])
        if not org_records:
            raise fastapi.HTTPException(
                status_code=409,
                detail=(
                    'No organization exists yet; create one before adding'
                    ' auth providers'
                ),
            )
        resolved_org_slug = str(graph.parse_agtype(org_records[0]['slug']))

    # AGE doesn't support ON CREATE SET, so use COALESCE to leave
    # existing service attributes untouched when they're already
    # populated. The org is REQUIRED to exist (we don't auto-create);
    # only the synthetic ThirdPartyService is MERGEd.
    create_query: str = (
        'MATCH (o:Organization {{slug: {org_slug}}})'
        ' MERGE (s:ThirdPartyService {{slug: {svc_slug}}})'
        ' -[:BELONGS_TO]->(o)'
        ' SET s.name = COALESCE(s.name, {svc_name}),'
        ' s.vendor = COALESCE(s.vendor, {svc_vendor}),'
        " s.status = COALESCE(s.status, 'active'),"
        " s.identifiers = COALESCE(s.identifiers, '{{}}'),"
        " s.links = COALESCE(s.links, '{{}}')"
        ' WITH s, o'
        f' CREATE (a:ServiceApplication {app_tpl})'
        ' CREATE (a)-[:REGISTERED_IN]->(s)'
        ' RETURN a{{.*}} AS app, s{{.*}} AS service,'
        ' o{{.*}} AS organization'
    )
    try:
        records = await db.execute(
            create_query,
            {
                'svc_slug': resolved_service_slug,
                'svc_name': service_label,
                'svc_vendor': _OAUTH_APP_TYPE_LABELS[data.oauth_app_type],
                'org_slug': resolved_org_slug,
                **create_props,
            },
            ['app', 'service', 'organization'],
        )
    except psycopg.errors.UniqueViolation as e:
        raise fastapi.HTTPException(
            status_code=409,
            detail=f'Auth provider {resolved_slug!r} already exists',
        ) from e

    if not records:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Organization {resolved_org_slug!r} not found',
        )

    login_providers.invalidate_cache(resolved_slug)
    app = graph.parse_agtype(records[0]['app'])
    svc = graph.parse_agtype(records[0].get('service'))
    org = graph.parse_agtype(records[0].get('organization'))
    LOGGER.info(
        'Auth provider %s created by %s', resolved_slug, auth.principal_name
    )
    return AuthProviderResponse(**_row_to_response(app, svc, org))


@auth_providers_router.put('/{slug}', response_model=AuthProviderResponse)
async def update_auth_provider(
    slug: str,
    data: AuthProviderUpdate,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('auth_providers:write')
        ),
    ],
) -> AuthProviderResponse:
    """Update a login-eligible service application.

    A blank/missing ``client_secret`` preserves the existing encrypted
    secret on the row.
    """
    existing = await db.execute(
        _FETCH_BY_SLUG, {'slug': slug}, ['app', 'service', 'organization']
    )
    if not existing:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Auth provider {slug!r} not found',
        )
    existing_app = graph.parse_agtype(existing[0]['app'])
    if existing_app.get('usage') not in ('login', 'both'):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Auth provider {slug!r} not found',
        )

    update_props: dict[str, typing.Any] = {
        'name': data.name,
        'description': data.description,
        'usage': data.usage,
        'oauth_app_type': data.oauth_app_type,
        'client_id': data.client_id,
        'issuer_url': data.issuer_url,
        'allowed_domains': json.dumps(list(data.allowed_domains)),
        'scopes': json.dumps(list(data.scopes)),
    }
    if data.client_secret:
        encryptor = encryption.TokenEncryption.get_instance()
        update_props['client_secret'] = encryptor.encrypt(data.client_secret)

    set_stmt = set_clause('a', update_props)
    update_query: str = (
        'MATCH (a:ServiceApplication {{slug: {slug}}})'
        f' {set_stmt}'
        ' RETURN a{{.*}} AS app'
    )
    await db.execute(update_query, {'slug': slug, **update_props}, ['app'])

    login_providers.invalidate_cache(slug)
    records = await db.execute(
        _FETCH_BY_SLUG, {'slug': slug}, ['app', 'service', 'organization']
    )
    app = graph.parse_agtype(records[0]['app'])
    svc = graph.parse_agtype(records[0].get('service'))
    org = graph.parse_agtype(records[0].get('organization'))
    LOGGER.info('Auth provider %s updated by %s', slug, auth.principal_name)
    return AuthProviderResponse(**_row_to_response(app, svc, org))


@auth_providers_router.delete('/{slug}', status_code=204)
async def delete_auth_provider(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('auth_providers:write')
        ),
    ],
) -> None:
    """Delete a login-only service application.

    Refuses ``usage='both'`` rows: the integration face must be dropped
    first from the third-party-services screen.
    """
    existing = await db.execute(
        _FETCH_BY_SLUG, {'slug': slug}, ['app', 'service', 'organization']
    )
    if not existing:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Auth provider {slug!r} not found',
        )
    existing_app = graph.parse_agtype(existing[0]['app'])
    usage = existing_app.get('usage')
    if usage not in ('login', 'both'):
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Auth provider {slug!r} not found',
        )
    if usage == 'both':
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                'Cannot delete a usage=both row from this screen; '
                "demote it to 'integration' from third-party-services first"
            ),
        )

    delete_query: typing.LiteralString = (
        'MATCH (a:ServiceApplication {{slug: {slug}}}) DETACH DELETE a'
    )
    await db.execute(delete_query, {'slug': slug})
    login_providers.invalidate_cache(slug)
    LOGGER.info('Auth provider %s deleted by %s', slug, auth.principal_name)


async def _transition_usage(
    db: graph.Graph,
    slug: str,
    expected_from: tuple[str, ...],
    new_usage: str,
) -> AuthProviderResponse:
    existing = await db.execute(
        _FETCH_BY_SLUG, {'slug': slug}, ['app', 'service', 'organization']
    )
    if not existing:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Auth provider {slug!r} not found',
        )
    existing_app = graph.parse_agtype(existing[0]['app'])
    current = existing_app.get('usage')
    if current not in expected_from:
        raise fastapi.HTTPException(
            status_code=409,
            detail=(
                f'Cannot transition usage from {current!r} via this endpoint'
            ),
        )
    update_query: typing.LiteralString = (
        'MATCH (a:ServiceApplication {{slug: {slug}}}) SET a.usage = {usage}'
    )
    await db.execute(update_query, {'slug': slug, 'usage': new_usage})
    login_providers.invalidate_cache(slug)
    records = await db.execute(
        _FETCH_BY_SLUG, {'slug': slug}, ['app', 'service', 'organization']
    )
    app = graph.parse_agtype(records[0]['app'])
    svc = graph.parse_agtype(records[0].get('service'))
    org = graph.parse_agtype(records[0].get('organization'))
    return AuthProviderResponse(**_row_to_response(app, svc, org))


@auth_providers_router.post(
    '/{slug}/promote-to-both', response_model=AuthProviderResponse
)
async def promote_to_both(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('auth_providers:write')
        ),
    ],
) -> AuthProviderResponse:
    """Promote a ``usage='login'`` row to ``usage='both'``."""
    return await _transition_usage(db, slug, ('login',), 'both')


@auth_providers_router.post(
    '/{slug}/demote-to-login', response_model=AuthProviderResponse
)
async def demote_to_login(
    slug: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('auth_providers:write')
        ),
    ],
) -> AuthProviderResponse:
    """Demote a ``usage='both'`` row back to ``usage='login'``."""
    return await _transition_usage(db, slug, ('both',), 'login')
