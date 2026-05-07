"""Identity hydration: thread per-user credentials into PluginContext."""

import datetime
import logging
import typing

from imbi_common import graph
from imbi_common.plugins.base import (
    IdentityCredentials,
    IdentityPlugin,
    PluginContext,
)
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import get_plugin

from imbi_api.identity import errors as identity_errors
from imbi_api.identity import repository
from imbi_api.plugins import parse_options

LOGGER = logging.getLogger(__name__)


def _start_url_for(plugin_id: str) -> str:
    """Build the canonical start URL for a plugin connect flow."""
    return f'/me/identities/{plugin_id}/start'


async def hydrate_identity(
    db: graph.Graph,
    ctx: PluginContext,
    identity_plugin_id: str,
    *,
    identity_options: dict[str, typing.Any] | None = None,
) -> PluginContext:
    """Load the actor's connection for ``identity_plugin_id`` and attach
    materialized credentials to ``ctx.identity``.

    Raises :class:`identity_errors.IdentityRequiredError` when the actor
    has no active connection.
    """
    user_id = ctx.actor_user_id
    if not user_id:
        raise identity_errors.IdentityRequiredError(
            plugin_id=identity_plugin_id,
            start_url=_start_url_for(identity_plugin_id),
        )

    connection = await repository.load_connection(
        db, identity_plugin_id, user_id
    )
    if connection is None or connection.status != 'active':
        raise identity_errors.IdentityRequiredError(
            plugin_id=identity_plugin_id,
            start_url=_start_url_for(identity_plugin_id),
        )

    # Look up the identity plugin's slug + handler so we can call
    # ``materialize`` for plugins that exchange the IdP token (AWS IAM IC).
    slug = await _plugin_slug(db, identity_plugin_id)
    if slug is None:
        raise identity_errors.IdentityRequiredError(
            plugin_id=identity_plugin_id,
            start_url=_start_url_for(identity_plugin_id),
        )

    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        LOGGER.error('Identity plugin %r unavailable for hydrate', slug)
        raise identity_errors.IdentityRequiredError(
            plugin_id=identity_plugin_id,
            start_url=_start_url_for(identity_plugin_id),
        ) from exc

    handler = entry.handler_cls()
    if not isinstance(handler, IdentityPlugin):
        raise identity_errors.IdentityRequiredError(
            plugin_id=identity_plugin_id,
            start_url=_start_url_for(identity_plugin_id),
        )

    base_credentials = IdentityCredentials(
        access_token=connection.access_token,
        refresh_token=connection.refresh_token,
        expires_at=connection.expires_at,
        scopes=connection.scopes,
    )

    if identity_options is None:
        identity_options = await load_plugin_options(db, identity_plugin_id)

    materialized = await handler.materialize(
        ctx,
        {},
        base_credentials,
        db=db,
        identity_options=identity_options,
    )

    return ctx.model_copy(update={'identity': materialized})


async def _plugin_slug(db: graph.Graph, plugin_id: str) -> str | None:
    query: typing.LiteralString = (
        'MATCH (p:Plugin {{id: {plugin_id}}}) '
        'RETURN p.plugin_slug AS slug LIMIT 1'
    )
    rows = await db.execute(query, {'plugin_id': plugin_id}, ['slug'])
    if not rows:
        return None
    parsed = graph.parse_agtype(rows[0]['slug'])
    return str(parsed) if parsed is not None else None


async def load_plugin_options(
    db: graph.Graph, plugin_id: str
) -> dict[str, typing.Any]:
    """Return the identity plugin instance's ``Plugin.options`` dict.

    Materialize implementations are expected to validate the keys they
    need; an empty dict is returned when the blob is absent.
    """
    query: typing.LiteralString = (
        'MATCH (p:Plugin {{id: {plugin_id}}}) '
        'RETURN p.options AS options LIMIT 1'
    )
    rows = await db.execute(query, {'plugin_id': plugin_id}, ['options'])
    if not rows:
        return {}
    return parse_options(graph.parse_agtype(rows[0]['options']))


def is_active(connection_expires_at: datetime.datetime | None) -> bool:
    """Return True if the connection's token is not yet expired."""
    if connection_expires_at is None:
        return True
    return connection_expires_at > datetime.datetime.now(datetime.UTC)
