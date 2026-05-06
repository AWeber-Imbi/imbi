"""High-level identity-flow operations: start, complete, refresh."""

import logging
import typing

from imbi_common import graph
from imbi_common.plugins.base import (
    IdentityCredentials,
    IdentityPlugin,
    IdentityProfile,
    PluginContext,
)
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import RegistryEntry, get_plugin

from imbi_api.identity import errors, repository, state
from imbi_api.plugins import credentials as plugin_credentials

LOGGER = logging.getLogger(__name__)


async def _load_plugin_handler(
    db: graph.Graph,
    plugin_id: str,
) -> tuple[RegistryEntry, IdentityPlugin, dict[str, str]]:
    """Look up the registered identity-plugin handler for ``plugin_id``.

    Returns ``(registry_entry, handler_instance, oauth_client_creds)``.
    Raises :class:`PluginNotFoundError` when the slug is not registered
    (caller maps to 404 / 503).
    """
    query: typing.LiteralString = (
        'MATCH (p:Plugin {{id: {plugin_id}}}) '
        'RETURN p.plugin_slug AS slug LIMIT 1'
    )
    rows = await db.execute(query, {'plugin_id': plugin_id}, ['slug'])
    if not rows:
        raise PluginNotFoundError(plugin_id)
    slug = graph.parse_agtype(rows[0]['slug'])
    entry = get_plugin(slug)
    handler = entry.handler_cls()
    if not isinstance(handler, IdentityPlugin):
        raise PluginNotFoundError(slug)
    creds = await plugin_credentials.get_plugin_credentials(
        db, plugin_id, entry
    )
    return entry, handler, creds


async def start_flow(
    db: graph.Graph,
    *,
    plugin_id: str,
    redirect_uri: str,
    actor_user_id: str | None,
    return_to: str | None = None,
    scopes: list[str] | None = None,
    intent: str = 'identity',
) -> tuple[str, str, typing.Any]:
    """Build the authorization URL + signed state token for a flow.

    Returns ``(authorization_url, state_token, polling_descriptor)``.
    The polling descriptor is ``None`` for redirect-based flows; for
    device-code plugins (AWS IAM IC) the UI uses it to render the user
    code and poll until the user completes the flow.
    """
    entry, handler, creds = await _load_plugin_handler(db, plugin_id)

    ctx = PluginContext(
        project_id='',
        project_slug='',
        org_slug='',
        actor_user_id=actor_user_id,
    )
    request = await handler.authorization_request(
        ctx,
        creds,
        redirect_uri,
        scopes or entry.manifest.default_scopes or None,
    )
    state_token = state.encode_identity_state(
        plugin_id=plugin_id,
        plugin_slug=entry.manifest.slug,
        redirect_uri=redirect_uri,
        intent=intent,
        return_to=return_to,
        code_verifier=request.code_verifier,
        actor_user_id=actor_user_id,
    )
    return request.authorization_url, state_token, request.polling


async def complete_flow(
    db: graph.Graph,
    *,
    code: str,
    state_token: str,
) -> tuple[IdentityProfile, IdentityCredentials, str, str | None]:
    """Exchange ``code`` for tokens and persist the connection.

    Returns ``(profile, credentials, plugin_id, return_to)``.  The caller
    decides whether to also create / refresh a session (login intent) or
    just record the IdentityConnection (identity intent).
    """
    state_data = state.decode_identity_state(state_token)
    plugin_id = state_data.plugin_id
    if not plugin_id:
        raise ValueError('state token missing plugin_id')

    _entry, handler, creds = await _load_plugin_handler(db, plugin_id)

    ctx = PluginContext(
        project_id='',
        project_slug='',
        org_slug='',
        actor_user_id=state_data.actor_user_id,
    )
    profile, credentials = await handler.exchange_code(
        ctx,
        creds,
        code,
        state_data.redirect_uri,
        state_data.code_verifier,
    )

    if state_data.actor_user_id:
        await repository.upsert_connection(
            db,
            plugin_id,
            state_data.actor_user_id,
            profile,
            credentials,
        )

    return profile, credentials, plugin_id, state_data.return_to


async def complete_login_flow(
    db: graph.Graph,
    *,
    code: str,
    state_token: str,
) -> tuple[IdentityProfile, IdentityCredentials, str, str | None]:
    """Exchange a code from an ``intent='login'`` flow.

    Mirrors :func:`complete_flow` but accepts a state token whose
    ``intent`` is ``'login'``.  Does *not* upsert an
    :class:`IdentityConnection` — the caller must provision the local
    user first and then call :func:`repository.upsert_connection` with
    that user's id.
    """
    state_data = state.decode_login_state(state_token)
    plugin_id = state_data.plugin_id
    if not plugin_id:
        raise ValueError('state token missing plugin_id')

    _entry, handler, creds = await _load_plugin_handler(db, plugin_id)
    ctx = PluginContext(
        project_id='',
        project_slug='',
        org_slug='',
    )
    profile, credentials = await handler.exchange_code(
        ctx,
        creds,
        code,
        state_data.redirect_uri,
        state_data.code_verifier,
    )
    return profile, credentials, plugin_id, state_data.return_to


async def refresh_connection(
    db: graph.Graph,
    *,
    plugin_id: str,
    actor_user_id: str,
) -> IdentityCredentials:
    """Force-refresh the actor's connection for ``plugin_id``."""
    connection = await repository.load_connection(db, plugin_id, actor_user_id)
    if connection is None:
        raise errors.IdentityRequiredError(
            plugin_id=plugin_id,
            start_url=f'/me/identities/{plugin_id}/start',
        )
    if not connection.refresh_token:
        raise errors.IdentityRefreshFailed(
            'No refresh token on this connection'
        )
    _entry, handler, creds = await _load_plugin_handler(db, plugin_id)
    ctx = PluginContext(
        project_id='',
        project_slug='',
        org_slug='',
        actor_user_id=actor_user_id,
    )
    try:
        new_credentials = await handler.refresh(
            ctx, creds, connection.refresh_token
        )
    except Exception as exc:
        await repository.mark_status(db, connection.connection_id, 'expired')
        raise errors.IdentityRefreshFailed(str(exc)) from exc

    profile = IdentityProfile(subject=connection.subject)
    await repository.upsert_connection(
        db,
        plugin_id,
        actor_user_id,
        profile,
        new_credentials,
    )
    return new_credentials


async def revoke_connection(
    db: graph.Graph,
    *,
    plugin_id: str,
    actor_user_id: str,
) -> None:
    """Best-effort revoke at the IdP, then mark the connection revoked."""
    connection = await repository.load_connection(db, plugin_id, actor_user_id)
    if connection is None:
        return
    try:
        _entry, handler, creds = await _load_plugin_handler(db, plugin_id)
        ctx = PluginContext(
            project_id='',
            project_slug='',
            org_slug='',
            actor_user_id=actor_user_id,
        )
        await handler.revoke(ctx, creds, connection.access_token)
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            'IdP revoke failed for plugin_id=%s user_id=%s; '
            'marking connection revoked anyway',
            plugin_id,
            actor_user_id,
            exc_info=True,
        )
    await repository.revoke(db, plugin_id, actor_user_id)
