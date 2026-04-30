"""Login-provider repository.

Reads ``ServiceApplication`` rows whose ``usage`` is ``'login'`` or
``'both'``, joined to their parent ``ThirdPartyService`` for the OAuth
endpoints. Cross-org by design — login providers are an instance-level
concern even though each row is owned by a single organization.

A 30s in-memory TTL cache keeps the OAuth hot path off the graph.
"""

from __future__ import annotations

import logging
import time
import typing

import pydantic
from imbi_common import graph

from imbi_api import settings

LOGGER = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30.0

_provider_cache: dict[str, tuple[LoginApp, float]] = {}
_list_cache: dict[bool, tuple[list[LoginApp], float]] = {}


class LoginApp(pydantic.BaseModel):
    """Flat view of a login-eligible ``ServiceApplication`` row.

    Combines the application row with the OAuth endpoints from the
    parent ``ThirdPartyService`` so callers don't need to traverse the
    graph again.
    """

    model_config = pydantic.ConfigDict(extra='ignore')

    slug: str
    name: str
    oauth_app_type: typing.Literal['google', 'github', 'oidc']
    client_id: str | None = None
    client_secret_encrypted: str | None = None
    issuer_url: str | None = None
    allowed_domains: list[str] = pydantic.Field(default_factory=list)
    scopes: list[str] = pydantic.Field(default_factory=list)
    status: str = 'active'
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    revoke_endpoint: str | None = None
    callback_url: str = ''


def invalidate_cache(slug: str | None = None) -> None:
    """Drop cached entries.

    ``slug=None`` clears everything; otherwise only the slug + lists.
    """
    if slug is None:
        _provider_cache.clear()
    else:
        _provider_cache.pop(slug, None)
    _list_cache.clear()


_LIST_QUERY: typing.LiteralString = """
MATCH (a:ServiceApplication)-[:REGISTERED_IN]->(s:ThirdPartyService)
WHERE a.usage IN ['login', 'both']
RETURN a{{.*}} AS app, s{{.*}} AS service
ORDER BY a.slug
"""


def _row_to_login_app(
    app: dict[str, typing.Any],
    svc: dict[str, typing.Any] | None,
) -> LoginApp:
    """Materialize a ``LoginApp`` from raw graph dicts."""
    raw_scopes = app.get('scopes')
    if isinstance(raw_scopes, str):
        import json as _json

        try:
            scopes = _json.loads(raw_scopes)
        except (ValueError, TypeError):
            scopes = []
    else:
        scopes = list(raw_scopes) if raw_scopes else []
    raw_domains = app.get('allowed_domains')
    if isinstance(raw_domains, str):
        import json as _json

        try:
            domains = _json.loads(raw_domains)
        except (ValueError, TypeError):
            domains = []
    else:
        domains = list(raw_domains) if raw_domains else []
    return LoginApp(
        slug=app['slug'],
        name=app.get('name', app['slug']),
        oauth_app_type=app['oauth_app_type'],
        client_id=app.get('client_id'),
        client_secret_encrypted=app.get('client_secret'),
        issuer_url=app.get('issuer_url'),
        allowed_domains=domains,
        scopes=scopes,
        status=app.get('status', 'active'),
        authorization_endpoint=(
            svc.get('authorization_endpoint') if svc else None
        ),
        token_endpoint=svc.get('token_endpoint') if svc else None,
        revoke_endpoint=svc.get('revoke_endpoint') if svc else None,
        callback_url=settings.oauth_callback_url(app['slug']),
    )


async def list_login_apps(
    db: graph.Graph,
    *,
    enabled_only: bool = False,
) -> list[LoginApp]:
    """Return every ``ServiceApplication`` flagged for login use.

    Cached per ``enabled_only`` for ``_CACHE_TTL_SECONDS``.
    """
    cached = _list_cache.get(enabled_only)
    now = time.time()
    if cached is not None and (now - cached[1]) < _CACHE_TTL_SECONDS:
        return list(cached[0])

    records = await db.execute(_LIST_QUERY, {}, ['app', 'service'])
    apps: list[LoginApp] = []
    for record in records:
        app = graph.parse_agtype(record['app'])
        svc = graph.parse_agtype(record.get('service'))
        if not app.get('oauth_app_type'):
            continue
        login_app = _row_to_login_app(app, svc)
        if enabled_only and login_app.status != 'active':
            continue
        apps.append(login_app)
    _list_cache[enabled_only] = (list(apps), now)
    return apps


_GET_QUERY: typing.LiteralString = """
MATCH (a:ServiceApplication {{slug: {slug}}})
      -[:REGISTERED_IN]->(s:ThirdPartyService)
WHERE a.usage IN ['login', 'both']
RETURN a{{.*}} AS app, s{{.*}} AS service
"""


async def get_login_app(db: graph.Graph, slug: str) -> LoginApp | None:
    """Look up a single login app by slug."""
    cached = _provider_cache.get(slug)
    now = time.time()
    if cached is not None and (now - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    records = await db.execute(_GET_QUERY, {'slug': slug}, ['app', 'service'])
    if not records:
        return None
    app = graph.parse_agtype(records[0]['app'])
    svc = graph.parse_agtype(records[0].get('service'))
    if not app.get('oauth_app_type'):
        return None
    login_app = _row_to_login_app(app, svc)
    _provider_cache[slug] = (login_app, now)
    return login_app
