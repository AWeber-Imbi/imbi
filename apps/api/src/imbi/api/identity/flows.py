"""High-level identity-flow operations: start, complete, refresh."""

import json
import logging
import typing
import urllib.parse

from imbi_common import graph
from imbi_common.plugins.base import (
    IdentityCredentials,
    IdentityPlugin,
    IdentityProfile,
    PluginContext,
)
from imbi_common.plugins.errors import PluginNotFoundError
from imbi_common.plugins.registry import RegistryEntry, get_plugin
from valkey import asyncio as valkey

from imbi_api.identity import errors, repository, state
from imbi_api.plugins import credentials as plugin_credentials

LOGGER = logging.getLogger(__name__)


async def _load_plugin_handler(
    db: graph.Graph,
    plugin_id: str,
) -> tuple[
    str, RegistryEntry, IdentityPlugin, dict[str, str], dict[str, typing.Any]
]:
    """Resolve ``plugin_id`` and load handler, credentials, and options.

    ``plugin_id`` may be either a ``:Plugin`` node id (Phase-1
    service-attached plugin instance) or a manifest slug (the
    user-driven Connections page sends the slug because the catalog
    surface doesn't expose node ids).

    When a ``:Plugin`` node matches, its ``options`` JSON is parsed and
    returned for the caller to thread through ``PluginContext``.
    Without a node, options/credentials default to empty dicts and
    plugins with required manifest options will surface their own
    error from ``authorization_request``.

    Returns ``(resolved_plugin_id, entry, handler, creds, options)``.
    Raises :class:`PluginNotFoundError` when nothing resolves.
    """
    by_id: typing.LiteralString = (
        'MATCH (p:Plugin {{id: {plugin_id}}}) '
        'RETURN p.id AS id, p.plugin_slug AS slug, p.options AS options '
        'LIMIT 1'
    )
    rows = await db.execute(
        by_id, {'plugin_id': plugin_id}, ['id', 'slug', 'options']
    )
    if not rows:
        by_slug: typing.LiteralString = (
            'MATCH (p:Plugin {{plugin_slug: {plugin_id}}}) '
            'RETURN p.id AS id, p.plugin_slug AS slug, p.options AS options '
            'LIMIT 1'
        )
        rows = await db.execute(
            by_slug, {'plugin_id': plugin_id}, ['id', 'slug', 'options']
        )

    if rows:
        resolved_id = graph.parse_agtype(rows[0]['id'])
        slug = graph.parse_agtype(rows[0]['slug'])
        options = _parse_options(rows[0].get('options'))
    else:
        resolved_id = plugin_id
        slug = plugin_id
        options = {}

    try:
        entry = get_plugin(slug)
    except PluginNotFoundError as exc:
        raise PluginNotFoundError(plugin_id) from exc
    handler = entry.handler_cls()
    if not isinstance(handler, IdentityPlugin):
        raise PluginNotFoundError(slug)
    creds = await plugin_credentials.get_plugin_credentials(
        db, resolved_id, entry
    )
    return resolved_id, entry, handler, creds, options


def _parse_options(raw: typing.Any) -> dict[str, typing.Any]:
    """Decode the ``Plugin.options`` agtype value into a dict.

    Stored as a JSON-encoded string per ``service_plugins.create``;
    accept dicts defensively for backward compatibility.
    """
    if raw is None:
        return {}
    parsed = graph.parse_agtype(raw)
    if isinstance(parsed, dict):
        return typing.cast('dict[str, typing.Any]', parsed)
    if isinstance(parsed, str):
        try:
            decoded = json.loads(parsed)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return typing.cast('dict[str, typing.Any]', decoded)
        return {}
    return {}


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
    resolved_id, entry, handler, creds, options = await _load_plugin_handler(
        db, plugin_id
    )

    ctx = PluginContext(
        project_id='',
        project_slug='',
        org_slug='',
        actor_user_id=actor_user_id,
        assignment_options=options,
    )
    request = await handler.authorization_request(
        ctx,
        creds,
        redirect_uri,
        scopes or entry.manifest.default_scopes or None,
    )
    # Plugins that self-mint client credentials during
    # ``authorization_request`` (e.g. AWS IAM IC's dynamic OIDC
    # registration) surface them on the request so we can persist
    # them -- the matching ``exchange_code`` is invoked from
    # ``poll_flow``, which only sees credentials read from storage,
    # not the in-memory ones the plugin just created.
    if request.registered_credentials is not None:
        updates: dict[str, str | None] = dict(request.registered_credentials)
        await plugin_credentials.patch_plugin_configuration(
            db, resolved_id, updates
        )
    # Device-code flows have no redirect to echo a code back on, so
    # carry the IdP-issued ``deviceCode`` (returned by the plugin via
    # ``AuthorizationRequest.state``) inside the signed state token —
    # the poll endpoint pulls it back out to call ``CreateToken``.
    device_code = request.state if request.polling else None
    state_token = state.encode_identity_state(
        plugin_id=resolved_id,
        plugin_slug=entry.manifest.slug,
        redirect_uri=redirect_uri,
        intent=intent,
        return_to=return_to,
        code_verifier=request.code_verifier,
        actor_user_id=actor_user_id,
        device_code=device_code,
    )
    # Plugins mint a random ``state`` nonce internally for CSRF, but the
    # callback handler decodes the IdP-echoed ``state`` as the signed
    # identity-flow JWT.  Replace the plugin's nonce with the JWT in the
    # authorization URL so the round-trip carries the trusted token.
    # Skipped for device-code flows, which never round-trip ``state``
    # through the IdP and reuse ``request.state`` as the device code.
    authorization_url = (
        request.authorization_url
        if request.polling
        else _replace_state(request.authorization_url, state_token)
    )
    return authorization_url, state_token, request.polling


_LOCAL_HOSTS = frozenset({'localhost', '127.0.0.1', '::1'})


def _replace_state(url: str, state_token: str) -> str:
    """Return ``url`` with its ``state`` param set to ``state_token``.

    Refuses to rewrite non-HTTPS authorization URLs (except for the
    local-loopback hosts that dev / test fixtures legitimately use).
    The state JWT carries signed flow context we don't want round-
    tripped over an unencrypted redirect, and a misconfigured plugin
    manifest pointing at ``http://idp.example.com`` would otherwise
    silently expose it to anyone on the network path.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' and parts.hostname not in _LOCAL_HOSTS:
        raise ValueError(
            f'Identity-flow authorization URL must use https; got {url!r}'
        )
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    rewritten = [(k, state_token if k == 'state' else v) for k, v in query]
    if not any(k == 'state' for k, _ in query):
        rewritten.append(('state', state_token))
    return urllib.parse.urlunsplit(
        parts._replace(query=urllib.parse.urlencode(rewritten))
    )


async def complete_flow(
    db: graph.Graph,
    *,
    code: str,
    state_token: str,
    valkey_client: valkey.Valkey | None,
) -> tuple[IdentityProfile, IdentityCredentials, str, str | None]:
    """Exchange ``code`` for tokens and persist the connection.

    Returns ``(profile, credentials, plugin_id, return_to)``.  The caller
    decides whether to also create / refresh a session (login intent) or
    just record the IdentityConnection (identity intent).

    Enforces single-use semantics on the state JWT's nonce via
    :func:`state.consume_identity_nonce` so a leaked / logged state
    cannot be replayed within its 10-minute TTL.
    """
    state_data = state.decode_identity_state(state_token)
    plugin_id = state_data.plugin_id
    if not plugin_id:
        raise ValueError('state token missing plugin_id')
    if not await state.consume_identity_nonce(valkey_client, state_data.nonce):
        raise ValueError('state token has already been used')

    resolved_id, _entry, handler, creds, options = await _load_plugin_handler(
        db, plugin_id
    )

    ctx = PluginContext(
        project_id='',
        project_slug='',
        org_slug='',
        actor_user_id=state_data.actor_user_id,
        assignment_options=options,
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
            resolved_id,
            state_data.actor_user_id,
            profile,
            credentials,
        )

    return profile, credentials, resolved_id, state_data.return_to


async def poll_flow(
    db: graph.Graph,
    *,
    state_token: str,
) -> tuple[IdentityProfile, IdentityCredentials, str, str | None]:
    """Drive one poll tick of an OAuth 2.0 device-code identity flow.

    Decodes ``state_token`` to recover the IdP-issued ``device_code``
    (signed in by :func:`start_flow`), then calls the plugin handler's
    ``exchange_code``.  Re-raises :class:`IdentityAuthorizationPending`
    when the user hasn't completed the flow yet — callers map that to
    HTTP 202.  On success the connection is persisted exactly like
    :func:`complete_flow` does for redirect flows.
    """
    state_data = state.decode_identity_state(state_token)
    plugin_id = state_data.plugin_id
    if not plugin_id:
        raise ValueError('state token missing plugin_id')
    if not state_data.device_code:
        raise ValueError('state token missing device_code (not a device flow)')

    resolved_id, _entry, handler, creds, options = await _load_plugin_handler(
        db, plugin_id
    )

    ctx = PluginContext(
        project_id='',
        project_slug='',
        org_slug='',
        actor_user_id=state_data.actor_user_id,
        assignment_options=options,
    )
    profile, credentials = await handler.exchange_code(
        ctx,
        creds,
        state_data.device_code,
        state_data.redirect_uri,
        state_data.code_verifier,
    )

    if state_data.actor_user_id:
        await repository.upsert_connection(
            db,
            resolved_id,
            state_data.actor_user_id,
            profile,
            credentials,
        )

    return profile, credentials, resolved_id, state_data.return_to


async def complete_login_flow(
    db: graph.Graph,
    *,
    code: str,
    state_token: str,
    valkey_client: valkey.Valkey | None,
) -> tuple[IdentityProfile, IdentityCredentials, str, str | None]:
    """Exchange a code from an ``intent='login'`` flow.

    Mirrors :func:`complete_flow` but accepts a state token whose
    ``intent`` is ``'login'``.  Does *not* upsert an
    :class:`IdentityConnection` — the caller must provision the local
    user first and then call :func:`repository.upsert_connection` with
    that user's id.

    The state JWT's nonce is enforced single-use via Valkey to prevent
    replay of a leaked or logged login state.
    """
    state_data = state.decode_login_state(state_token)
    plugin_id = state_data.plugin_id
    if not plugin_id:
        raise ValueError('state token missing plugin_id')
    if not await state.consume_identity_nonce(valkey_client, state_data.nonce):
        raise ValueError('state token has already been used')

    resolved_id, _entry, handler, creds, options = await _load_plugin_handler(
        db, plugin_id
    )
    ctx = PluginContext(
        project_id='',
        project_slug='',
        org_slug='',
        assignment_options=options,
    )
    profile, credentials = await handler.exchange_code(
        ctx,
        creds,
        code,
        state_data.redirect_uri,
        state_data.code_verifier,
    )
    return profile, credentials, resolved_id, state_data.return_to


async def refresh_connection(
    db: graph.Graph,
    *,
    plugin_id: str,
    actor_user_id: str,
) -> IdentityCredentials:
    """Force-refresh the actor's connection for ``plugin_id``."""
    resolved_id, _entry, handler, creds, options = await _load_plugin_handler(
        db, plugin_id
    )
    connection = await repository.load_connection(
        db, resolved_id, actor_user_id
    )
    if connection is None:
        raise errors.IdentityRequiredError(
            plugin_id=plugin_id,
            start_url=f'/me/identities/{plugin_id}/start',
        )
    if not connection.refresh_token:
        raise errors.IdentityRefreshFailed(
            'No refresh token on this connection'
        )
    ctx = PluginContext(
        project_id='',
        project_slug='',
        org_slug='',
        actor_user_id=actor_user_id,
        assignment_options=options,
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
        resolved_id,
        actor_user_id,
        profile,
        new_credentials,
    )
    return new_credentials


class RevokeOutcome(typing.TypedDict):
    """Outcome of :func:`revoke_connection`.

    ``idp_revoked`` is False when the IdP-side revoke call raised; the
    local connection is still revoked in that case but the caller
    needs to surface the partial state so the user knows the IdP
    still holds live credentials.
    """

    idp_revoked: bool
    idp_error: str | None


async def revoke_connection(
    db: graph.Graph,
    *,
    plugin_id: str,
    actor_user_id: str,
) -> RevokeOutcome:
    """First DELETE on an active connection: best-effort revoke at the
    IdP, then mark the connection revoked.  Subsequent DELETE on an
    already revoked / expired connection: hard-delete the node so the
    "Forget" action removes the row from the UI.

    Returns a :class:`RevokeOutcome` so the caller can distinguish a
    clean revoke from "we revoked locally but the IdP rejected our
    call." Cases where there's nothing to revoke at the IdP (plugin
    uninstalled, status was already non-active, no connection on
    file) are reported as ``idp_revoked=True`` because nothing
    *needed* IdP-side action.
    """
    try:
        (
            resolved_id,
            _entry,
            handler,
            creds,
            options,
        ) = await _load_plugin_handler(db, plugin_id)
    except PluginNotFoundError:
        # Plugin uninstalled out from under us.  Nothing to revoke at
        # the IdP; just hard-delete whatever's left so the UI can clear.
        await repository.delete_connection(db, plugin_id, actor_user_id)
        return {'idp_revoked': True, 'idp_error': None}

    status = await repository.connection_status(db, resolved_id, actor_user_id)
    if status is None:
        return {'idp_revoked': True, 'idp_error': None}
    if status != 'active':
        # Already revoked / expired — second DELETE means "forget."
        await repository.delete_connection(db, resolved_id, actor_user_id)
        return {'idp_revoked': True, 'idp_error': None}

    connection = await repository.load_connection(
        db, resolved_id, actor_user_id
    )
    idp_error: str | None = None
    if connection is not None:
        try:
            ctx = PluginContext(
                project_id='',
                project_slug='',
                org_slug='',
                actor_user_id=actor_user_id,
                assignment_options=options,
            )
            await handler.revoke(ctx, creds, connection.access_token)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                'IdP revoke failed for plugin_id=%s user_id=%s; '
                'marking connection revoked anyway',
                plugin_id,
                actor_user_id,
                exc_info=True,
            )
            idp_error = f'{type(exc).__name__}: {exc}'
    await repository.revoke(db, resolved_id, actor_user_id)
    return {'idp_revoked': idp_error is None, 'idp_error': idp_error}
