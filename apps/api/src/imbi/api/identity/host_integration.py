"""Helpers for the host-side wiring of capability identity hydration.

Capability endpoints (``configuration``, ``logs``, ``deployment``, ...)
construct a :class:`PluginContext` and then invoke a capability handler.
When the resolved capability's binding carries an
``identity_integration_id``, the API must:

1. Stamp the actor's user id onto the context.
2. Load the actor's identity connection for that Integration and attach
   materialized credentials to ``ctx.identity``.
3. Translate :class:`IdentityRequiredError` into the
   ``401`` / ``WWW-Authenticate: Imbi-Identity`` response shape so the
   UI knows which Integration to surface a Connect button for.

This module exists so each call site is a single one-liner instead of
duplicating the try/except + actor stamping + 401 mapping across every
capability endpoint.
"""

from __future__ import annotations

import collections.abc
import logging
import typing

import fastapi
from imbi_common import graph
from imbi_common.plugins import PluginAuthenticationFailed, PluginContext

from imbi_api.auth import permissions
from imbi_api.identity import errors as identity_errors
from imbi_api.identity import resolution as identity_resolution
from imbi_api.plugins.resolution import ResolvedCapability

LOGGER = logging.getLogger(__name__)

T = typing.TypeVar('T')


async def attach_identity(
    db: graph.Graph,
    ctx: PluginContext,
    resolved: ResolvedCapability,
    auth: permissions.AuthContext,
    *,
    identity_options: dict[str, typing.Any] | None = None,
) -> PluginContext:
    """Hydrate ``ctx.identity`` for a capability call.

    Stamps ``actor_user_id`` regardless of whether an identity
    Integration is bound — downstream capabilities may want to attribute
    calls to the human even when no per-user IdP is involved.

    When ``resolved.identity_integration_id`` is set, looks up the
    actor's :class:`IdentityConnection` and threads the materialized
    credentials into ``ctx.identity``.  Raises
    :class:`fastapi.HTTPException` with the
    ``identity_required`` shape (401 +
    ``WWW-Authenticate: Imbi-Identity integration_id=<id>``) when the
    actor has no active connection.

    ``identity_options`` lets a multi-call host (e.g. multi-env log
    fan-out) pre-load the identity Integration's capability options once
    and share them across N attaches instead of re-querying per call.
    """
    actor_user_id = auth.user.id if auth.user else None
    ctx = ctx.model_copy(update={'actor_user_id': actor_user_id})
    if not resolved.identity_integration_id:
        return ctx
    try:
        return await identity_resolution.hydrate_identity(
            db,
            ctx,
            resolved.identity_integration_id,
            identity_options=identity_options,
        )
    except identity_errors.IdentityRequiredError as exc:
        raise _identity_required_response(exc) from exc


async def call_with_identity_retry(
    db: graph.Graph,
    ctx: PluginContext,
    resolved: ResolvedCapability,
    auth: permissions.AuthContext,
    *,
    fn: collections.abc.Callable[
        [PluginContext], collections.abc.Awaitable[T]
    ],
    identity_options: dict[str, typing.Any] | None = None,
    attached: bool = False,
) -> T:
    """Invoke ``fn`` with hydrated identity, retrying once on 401.

    Combines :func:`attach_identity` with an automatic refresh-and-retry
    on :class:`PluginAuthenticationFailed`: when a capability's API call
    comes back as 401 (token expired between the sweeper's last refresh
    and now), the host calls :func:`flows.refresh_connection`,
    re-hydrates the context, and retries the call once.  A second 401 —
    or a refresh failure — surfaces as the canonical
    ``identity_required`` 401 so the UI can prompt the user to reconnect.

    Wrap each capability call site that may legitimately encounter token
    expiry mid-flight (configuration reads/writes, deployments,
    interactive log queries).  Background sweeps and one-shot CLI
    paths can still call :func:`attach_identity` directly when retry
    is undesirable.

    Pass ``attached=True`` when the caller has already invoked
    :func:`attach_identity` on ``ctx`` (e.g. shared resolve helpers
    that hydrate up-front for read paths) — saves an avoidable
    ``hydrate_identity`` round-trip on the happy path.  The retry
    branch always re-attaches regardless.
    """
    if not attached:
        ctx = await attach_identity(
            db, ctx, resolved, auth, identity_options=identity_options
        )
    try:
        return await fn(ctx)
    except PluginAuthenticationFailed as exc:
        integration_id = resolved.identity_integration_id
        if not integration_id or auth.user is None:
            raise
        LOGGER.info(
            'Integration %s returned 401 for user %s; refreshing identity '
            'and retrying once: %s',
            integration_id,
            auth.user.id,
            exc,
        )
        from imbi_api.identity import flows

        try:
            await flows.refresh_connection(
                db,
                integration_id=integration_id,
                actor_user_id=auth.user.id,
            )
        except identity_errors.IdentityRefreshFailed as refresh_exc:
            raise _identity_required_response(
                identity_errors.IdentityRequiredError(
                    integration_id=integration_id,
                    start_url=f'/me/identities/{integration_id}/start',
                )
            ) from refresh_exc

        ctx = await attach_identity(
            db, ctx, resolved, auth, identity_options=identity_options
        )
        return await fn(ctx)


def _identity_required_response(
    exc: identity_errors.IdentityRequiredError,
) -> fastapi.HTTPException:
    headers: dict[str, str] = {
        'WWW-Authenticate': (
            f'Imbi-Identity integration_id={exc.integration_id}'
        ),
    }
    detail: dict[str, typing.Any] = {
        'error': 'identity_required',
        'integration_id': exc.integration_id,
        'start_url': exc.start_url,
    }
    return fastapi.HTTPException(
        status_code=401, detail=detail, headers=headers
    )
