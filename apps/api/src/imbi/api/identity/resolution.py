"""Identity hydration: thread per-user credentials into PluginContext."""

import datetime
import logging
import typing

from imbi_common import graph
from imbi_common.plugins import (
    IdentityCapability,
    IdentityCredentials,
    PluginContext,
    PluginNotFoundError,
    decrypt_integration_credentials,
    get_capability,
)

from imbi_api.identity import errors as identity_errors
from imbi_api.identity import repository
from imbi_api.identity.models import IdentityCredentialsInternal
from imbi_api.plugins.assignments import capability_state, hydrate_integration

LOGGER = logging.getLogger(__name__)

# Refresh proactively when the access token expires within this many
# seconds.  Smaller than the sweeper's 5-minute lookahead so the two
# layers don't fight; this hook only catches the race between sweeper
# ticks.
_PROACTIVE_REFRESH_WINDOW_SECONDS = 60


def _start_url_for(integration_id: str) -> str:
    """Build the canonical start URL for an Integration connect flow."""
    return f'/me/identities/{integration_id}/start'


async def hydrate_identity(
    db: graph.Graph,
    ctx: PluginContext,
    integration_id: str,
    *,
    identity_options: dict[str, typing.Any] | None = None,
) -> PluginContext:
    """Load the actor's connection for ``integration_id`` and attach
    materialized credentials to ``ctx.identity``.

    Raises :class:`identity_errors.IdentityRequiredError` when the actor
    has no active connection.
    """
    user_id = ctx.actor_user_id
    if not user_id:
        raise identity_errors.IdentityRequiredError(
            integration_id=integration_id,
            start_url=_start_url_for(integration_id),
        )

    connection = await repository.load_connection(db, integration_id, user_id)
    if connection is None or connection.status != 'active':
        raise identity_errors.IdentityRequiredError(
            integration_id=integration_id,
            start_url=_start_url_for(integration_id),
        )

    if _should_refresh(connection):
        connection = await _refresh_and_reload(db, integration_id, user_id)

    # Load the Integration so we can resolve its plugin's identity
    # capability handler and decrypt its credentials for ``materialize``
    # (e.g. AWS IAM IC exchanges the IdP token for STS credentials).
    integration = await load_integration(db, integration_id)
    if integration is None:
        LOGGER.error(
            'Integration %r missing for identity hydration', integration_id
        )
        raise identity_errors.IdentityRequiredError(
            integration_id=integration_id,
            start_url=_start_url_for(integration_id),
        )

    plugin_slug = str(integration.get('plugin') or '')
    try:
        handler_cls = get_capability(plugin_slug, 'identity')
    except PluginNotFoundError as exc:
        LOGGER.error(
            'Identity capability unavailable for plugin %r (integration %r)',
            plugin_slug,
            integration_id,
        )
        raise identity_errors.IdentityRequiredError(
            integration_id=integration_id,
            start_url=_start_url_for(integration_id),
        ) from exc

    handler = typing.cast('IdentityCapability', handler_cls())
    credentials = decrypt_integration_credentials(
        integration.get('encrypted_credentials') or {}
    )

    base_credentials = IdentityCredentials(
        access_token=connection.access_token,
        refresh_token=connection.refresh_token,
        expires_at=connection.expires_at,
        scopes=connection.scopes,
    )

    if identity_options is None:
        identity_options = (
            capability_state(integration, 'identity').get('options') or {}
        )

    materialized = await handler.materialize(
        ctx,
        credentials,
        base_credentials,
        db=db,
        identity_options=identity_options,
    )

    return ctx.model_copy(update={'identity': materialized})


async def load_integration(
    db: graph.Graph, integration_id: str
) -> dict[str, typing.Any] | None:
    """Return the hydrated ``Integration`` node props, or ``None``."""
    query: typing.LiteralString = (
        'MATCH (i:Integration {{id: {integration_id}}}) RETURN i LIMIT 1'
    )
    rows = await db.execute(query, {'integration_id': integration_id}, ['i'])
    if not rows:
        return None
    props: typing.Any = graph.parse_agtype(rows[0]['i'])
    if not isinstance(props, dict):
        return None
    return hydrate_integration(typing.cast('dict[str, typing.Any]', props))


async def load_integration_org_slug(
    db: graph.Graph, integration_id: str
) -> str | None:
    """Return the slug of the Organization that owns ``integration_id``.

    ``organization`` is a ``BELONGS_TO`` edge, not a stored node
    property, so it has to be resolved via a separate traversal from
    the Integration's other (JSON-string) properties.
    """
    query: typing.LiteralString = (
        'MATCH (i:Integration {{id: {integration_id}}})'
        '-[:BELONGS_TO]->(o:Organization) '
        'RETURN o.slug AS slug LIMIT 1'
    )
    rows = await db.execute(
        query, {'integration_id': integration_id}, ['slug']
    )
    if not rows:
        return None
    slug = graph.parse_agtype(rows[0]['slug'])
    return str(slug) if slug else None


async def load_plugin_options(
    db: graph.Graph, integration_id: str
) -> dict[str, typing.Any]:
    """Return the identity Integration's ``capabilities.identity.options``.

    Materialize implementations are expected to validate the keys they
    need; an empty dict is returned when the blob is absent.
    """
    integration = await load_integration(db, integration_id)
    if integration is None:
        return {}
    return typing.cast(
        'dict[str, typing.Any]',
        capability_state(integration, 'identity').get('options') or {},
    )


def is_active(connection_expires_at: datetime.datetime | None) -> bool:
    """Return True if the connection's token is not yet expired."""
    if connection_expires_at is None:
        return True
    return connection_expires_at > datetime.datetime.now(datetime.UTC)


def _should_refresh(connection: IdentityCredentialsInternal) -> bool:
    """True when ``connection`` should be refreshed before hydration.

    Connections without a refresh token are skipped — the sweeper
    would have flipped them to ``expired`` if it could have refreshed
    them.
    """
    if not connection.refresh_token:
        return False
    if connection.expires_at is None:
        return False
    horizon = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        seconds=_PROACTIVE_REFRESH_WINDOW_SECONDS
    )
    return connection.expires_at <= horizon


async def _refresh_and_reload(
    db: graph.Graph,
    integration_id: str,
    user_id: str,
) -> IdentityCredentialsInternal:
    """Force-refresh the actor's connection and re-load it.

    On refresh failure the underlying flow marks the connection
    ``status='expired'``; we surface :class:`IdentityRequiredError`
    so the request gets the same 401 as a missing connection.
    """
    from imbi_api.identity import flows

    try:
        await flows.refresh_connection(
            db, integration_id=integration_id, actor_user_id=user_id
        )
    except identity_errors.IdentityRefreshFailed as exc:
        LOGGER.info(
            'Proactive refresh failed integration_id=%s user_id=%s: %s; '
            'returning IdentityRequired to caller',
            integration_id,
            user_id,
            exc,
        )
        raise identity_errors.IdentityRequiredError(
            integration_id=integration_id,
            start_url=_start_url_for(integration_id),
        ) from exc

    refreshed = await repository.load_connection(db, integration_id, user_id)
    if refreshed is None or refreshed.status != 'active':
        raise identity_errors.IdentityRequiredError(
            integration_id=integration_id,
            start_url=_start_url_for(integration_id),
        )
    return refreshed
