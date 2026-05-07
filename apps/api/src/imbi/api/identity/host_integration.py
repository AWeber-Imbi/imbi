"""Helpers for the host-side wiring of plugin identity hydration.

The ``configuration`` and ``logs`` endpoints construct a
:class:`PluginContext` and then invoke a plugin handler.  When the
plugin's :class:`USES_PLUGIN` edge carries an ``identity_plugin_id``,
the API must:

1. Stamp the actor's user id onto the context.
2. Load the actor's identity connection for that plugin and attach
   materialized credentials to ``ctx.identity``.
3. Translate :class:`IdentityRequiredError` into the
   ``401`` / ``WWW-Authenticate: Imbi-Identity`` response shape so the
   UI knows which plugin to surface a Connect button for.

This module exists so each call site is a single one-liner instead of
duplicating the try/except + actor stamping + 401 mapping seven times.
"""

from __future__ import annotations

import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins.base import PluginContext

from imbi_api.auth import permissions
from imbi_api.identity import errors as identity_errors
from imbi_api.identity import resolution as identity_resolution
from imbi_api.plugins.resolution import ResolvedPlugin

LOGGER = logging.getLogger(__name__)


async def attach_identity(
    db: graph.Graph,
    ctx: PluginContext,
    resolved: ResolvedPlugin,
    auth: permissions.AuthContext,
    *,
    identity_options: dict[str, typing.Any] | None = None,
) -> PluginContext:
    """Hydrate ``ctx.identity`` for a plugin call.

    Stamps ``actor_user_id`` regardless of whether an identity plugin
    is named — downstream plugins may want to attribute calls to the
    human even when no per-user IdP is involved.

    When ``resolved.identity_plugin_id`` is set, looks up the actor's
    :class:`IdentityConnection` and threads the materialized
    credentials into ``ctx.identity``.  Raises
    :class:`fastapi.HTTPException` with the
    ``identity_required`` shape (401 +
    ``WWW-Authenticate: Imbi-Identity plugin_id=<id>``) when the actor
    has no active connection.

    ``identity_options`` lets a multi-call host (e.g. multi-env log
    fan-out) pre-load the identity plugin's ``Plugin.options`` once
    and share them across N attaches instead of re-querying per call.
    """
    actor_user_id = auth.user.id if auth.user else None
    ctx = ctx.model_copy(update={'actor_user_id': actor_user_id})
    if not resolved.identity_plugin_id:
        return ctx
    try:
        return await identity_resolution.hydrate_identity(
            db,
            ctx,
            resolved.identity_plugin_id,
            identity_options=identity_options,
        )
    except identity_errors.IdentityRequiredError as exc:
        raise _identity_required_response(exc) from exc


def _identity_required_response(
    exc: identity_errors.IdentityRequiredError,
) -> fastapi.HTTPException:
    headers: dict[str, str] = {
        'WWW-Authenticate': f'Imbi-Identity plugin_id={exc.plugin_id}',
    }
    detail: dict[str, typing.Any] = {
        'error': 'identity_required',
        'plugin_id': exc.plugin_id,
        'start_url': exc.start_url,
    }
    return fastapi.HTTPException(
        status_code=401, detail=detail, headers=headers
    )
