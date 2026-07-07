"""Login-provider repository.

Plugin Architecture v3: a login provider is an ``Integration`` whose
plugin declares an ``identity`` capability with the ``login_capable``
hint, and whose node carries a direct ``used_as_login=true`` property
(set by the admin UI when promoting the Integration to a login
provider). There is exactly one source now -- the legacy
``ServiceApplication`` / hardcoded ``google``/``github``/``oidc`` rows
and the separate ``:Plugin`` node lookup are both gone.

A 30s in-memory TTL cache keeps the OAuth hot path off the graph.
"""

from __future__ import annotations

import logging
import time
import typing

import pydantic
from imbi_common import graph
from imbi_common.plugins import (
    PluginNotFoundError,
    decrypt_integration_credentials,
    get_plugin,
)

from imbi_api import settings
from imbi_api.plugins.assignments import (
    capability_enabled,
    hydrate_integration,
)

LOGGER = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30.0

_provider_cache: dict[str, tuple[LoginApp, float]] = {}
_list_cache: dict[bool, tuple[list[LoginApp], float]] = {}


class LoginApp(pydantic.BaseModel):
    """Flat view of a login-eligible Integration.

    Combines the Integration's decrypted OAuth credentials with its
    ``options`` (issuer URL, OAuth endpoints, etc.) so callers don't
    need to re-query the graph or decrypt anything themselves.
    """

    model_config = pydantic.ConfigDict(extra='ignore')

    slug: str
    name: str
    integration_id: str
    #: The plugin's declared ``auth_type`` (``oauth2``, ``oidc``,
    #: ``aws-iam-ic``, ...), or ``integration.options['oauth_app_type']``
    #: when the plugin overrides it.
    oauth_app_type: str
    client_id: str | None = None
    client_secret: str | None = None
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


_LOGIN_INTEGRATIONS_QUERY: typing.LiteralString = """
MATCH (i:Integration)
WHERE i.used_as_login = true
RETURN i
ORDER BY i.slug
"""

_LOGIN_INTEGRATION_QUERY: typing.LiteralString = """
MATCH (i:Integration {{slug: {slug}}})
WHERE i.used_as_login = true
RETURN i
LIMIT 1
"""


def _integration_to_login_app(
    integration: dict[str, typing.Any],
) -> LoginApp | None:
    """Materialize a ``LoginApp`` from a hydrated Integration, or
    ``None`` when its plugin doesn't declare a login-capable identity
    capability or the capability is disabled."""
    plugin_slug = str(integration.get('plugin') or '')
    try:
        entry = get_plugin(plugin_slug)
    except PluginNotFoundError:
        return None
    capability = entry.manifest.get_capability('identity')
    if capability is None or not capability.hints.get('login_capable'):
        return None
    if not capability_enabled(integration, 'identity'):
        return None

    options = typing.cast(
        'dict[str, typing.Any]', integration.get('options') or {}
    )
    credentials = decrypt_integration_credentials(
        typing.cast(
            'dict[str, str]', integration.get('encrypted_credentials') or {}
        )
    )
    slug = str(integration['slug'])
    return LoginApp(
        slug=slug,
        name=str(integration.get('name') or slug),
        integration_id=str(integration['id']),
        oauth_app_type=str(
            options.get('oauth_app_type') or entry.manifest.auth_type
        ),
        client_id=credentials.get('client_id'),
        client_secret=credentials.get('client_secret'),
        issuer_url=options.get('issuer_url'),
        allowed_domains=list(options.get('allowed_domains') or []),
        scopes=list(options.get('scopes') or []),
        status=str(integration.get('status') or 'active'),
        authorization_endpoint=options.get('authorization_endpoint'),
        token_endpoint=options.get('token_endpoint'),
        revoke_endpoint=options.get('revoke_endpoint'),
        callback_url=settings.oauth_callback_url(slug),
    )


async def list_login_apps(
    db: graph.Graph,
    *,
    enabled_only: bool = False,
) -> list[LoginApp]:
    """Return every login-eligible Integration.

    Cached per ``enabled_only`` for ``_CACHE_TTL_SECONDS``.
    """
    cached = _list_cache.get(enabled_only)
    now = time.time()
    if cached is not None and (now - cached[1]) < _CACHE_TTL_SECONDS:
        return list(cached[0])

    records = await db.execute(_LOGIN_INTEGRATIONS_QUERY, {}, ['i'])
    apps: list[LoginApp] = []
    for record in records:
        props: typing.Any = graph.parse_agtype(record['i'])
        if not isinstance(props, dict):
            continue
        typed_props = typing.cast('dict[str, typing.Any]', props)
        login_app = _integration_to_login_app(hydrate_integration(typed_props))
        if login_app is None:
            continue
        if enabled_only and login_app.status != 'active':
            continue
        apps.append(login_app)

    _list_cache[enabled_only] = (list(apps), now)
    return apps


async def get_login_app(db: graph.Graph, slug: str) -> LoginApp | None:
    """Look up a single login app by Integration slug."""
    cached = _provider_cache.get(slug)
    now = time.time()
    if cached is not None and (now - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    records = await db.execute(_LOGIN_INTEGRATION_QUERY, {'slug': slug}, ['i'])
    if not records:
        return None
    props: typing.Any = graph.parse_agtype(records[0]['i'])
    if not isinstance(props, dict):
        return None
    typed_props = typing.cast('dict[str, typing.Any]', props)
    login_app = _integration_to_login_app(hydrate_integration(typed_props))
    if login_app is None:
        return None
    _provider_cache[slug] = (login_app, now)
    return login_app
