"""User-facing identity flow endpoints (``/me/identities/*``)."""

import logging
import typing
import urllib.parse

import fastapi
import fastapi.responses
from imbi_common import graph
from imbi_common.plugins import (
    IdentityAuthorizationExpired,
    IdentityAuthorizationPending,
    PluginNotFoundError,
)

from imbi_api import settings
from imbi_api.auth import permissions
from imbi_api.identity import (
    errors,
    flows,
    models,
    repository,
)
from imbi_api.scoring import OptionalValkeyClient

LOGGER = logging.getLogger(__name__)


me_identities_router = fastapi.APIRouter(
    prefix='/me/identities', tags=['Identities']
)


def _is_safe_return_to(url: str | None) -> bool:
    """Return True if ``url`` is a safe in-app redirect target.

    ``return_to`` is user-supplied via :class:`IdentityConnectionStartRequest`
    and signed inside the state JWT, but the signature only proves the
    requester chose the value — not that it points back at the UI.  Reject
    anything with a scheme or netloc to avoid an open redirect that could
    chain a successful identity callback into a phishing page.  The value
    must also start with ``/`` (and not ``//`` which browsers treat as
    protocol-relative).
    """
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme or parsed.netloc:
        return False
    return url.startswith('/') and not url.startswith('//')


def _build_redirect_uri(request: fastapi.Request, integration_id: str) -> str:
    """Compute the absolute callback URL for a connect flow."""
    try:
        base = settings.get_server_config().public_base_url
    except Exception:  # noqa: BLE001
        base = ''
    if base:
        return f'{base.rstrip("/")}/me/identities/{integration_id}/callback'
    # Fallback: build from the inbound request — works in dev where
    # public_base_url isn't configured yet.
    scheme = request.url.scheme
    host = request.url.netloc
    return f'{scheme}://{host}/me/identities/{integration_id}/callback'


@me_identities_router.get('')
async def list_my_identities(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('me:identities:manage'),
        ),
    ],
) -> list[models.IdentityConnectionResponse]:
    """List the caller's identity connections."""
    user = auth.require_user
    rows = await repository.list_for_user(db, user.id)
    return [
        models.IdentityConnectionResponse(
            id=row['id'],
            integration_id=row['integration_id'],
            integration_slug=row.get('integration_slug') or '',
            integration_name=row.get('integration_name'),
            subject=row.get('subject') or '',
            status=row.get('status') or 'active',
            expires_at=row.get('expires_at'),
            scopes=list(row.get('scopes') or []),
            last_used_at=row.get('last_used_at'),
            metadata=row.get('metadata') or {},
        )
        for row in rows
    ]


@me_identities_router.post('/{integration_id}/start')
async def start_connect(
    integration_id: str,
    body: models.IdentityConnectionStartRequest,
    request: fastapi.Request,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('me:identities:manage'),
        ),
    ],
) -> models.IdentityConnectionStartResponse:
    """Begin a connect flow.

    Returns the authorization URL (and a polling descriptor for
    device-flow plugins).  The browser then either redirects to the
    URL (redirect flows) or polls ``/poll`` (device flows).
    """
    user = auth.require_user
    redirect_uri = _build_redirect_uri(request, integration_id)
    try:
        url, state_token, polling = await flows.start_flow(
            db,
            integration_id=integration_id,
            redirect_uri=redirect_uri,
            actor_user_id=user.id,
            return_to=body.return_to,
            scopes=body.scopes,
            intent='identity',
        )
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration {integration_id!r} not available',
        ) from exc
    return models.IdentityConnectionStartResponse(
        authorization_url=url, state=state_token, polling=polling
    )


@me_identities_router.post('/{integration_id}/poll')
async def poll_connect(
    integration_id: str,
    body: models.IdentityConnectionPollRequest,
    response: fastapi.Response,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('me:identities:manage'),
        ),
    ],
) -> models.IdentityConnectionPollResponse:
    """Drive one tick of a device-code identity flow.

    The UI calls this on a timer at the interval reported by the
    ``polling`` descriptor returned from ``/start``.  Returns
    ``status='pending'`` with HTTP 202 while the user is still
    authorizing at the IdP; ``status='complete'`` (HTTP 200) once
    tokens are persisted.  The ``return_to`` field, if set, mirrors
    the value the caller provided to ``/start`` so the UI can land
    the user back where they came from.
    """
    # Authentication is enforced by the dependency; the actor is also
    # signed into the state, but we still gate the endpoint.
    _ = auth
    try:
        (
            _profile,
            _credentials,
            _resolved_id,
            return_to,
        ) = await flows.poll_flow(db, state_token=body.state)
    except IdentityAuthorizationPending:
        response.status_code = 202
        return models.IdentityConnectionPollResponse(status='pending')
    except IdentityAuthorizationExpired as exc:
        raise fastapi.HTTPException(
            status_code=410, detail=f'Authorization expired: {exc}'
        ) from exc
    except ValueError as exc:
        raise fastapi.HTTPException(
            status_code=400, detail=f'Invalid state: {exc}'
        ) from exc
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration {integration_id!r} not available',
        ) from exc
    return models.IdentityConnectionPollResponse(
        status='complete', return_to=return_to
    )


@me_identities_router.get('/{integration_id}/callback')
async def callback(
    integration_id: str,
    code: str,
    state: str,
    db: graph.Pool,
    valkey_client: OptionalValkeyClient,
) -> fastapi.responses.Response:
    """Browser callback handler — exchanges ``code`` and persists the
    connection.  The state JWT carries the actor identity (the user may
    not have a session yet during a login flow) and its nonce is
    enforced single-use via Valkey to prevent replay."""
    try:
        (
            _profile,
            _credentials,
            _returned_integration_id,
            return_to,
        ) = await flows.complete_flow(
            db,
            code=code,
            state_token=state,
            valkey_client=valkey_client,
        )
    except ValueError as exc:
        raise fastapi.HTTPException(
            status_code=400, detail=f'Invalid state: {exc}'
        ) from exc
    except PluginNotFoundError as exc:
        raise fastapi.HTTPException(
            status_code=404,
            detail=f'Integration {integration_id!r} not available',
        ) from exc

    # The callback is served by the API, but the landing page is a UI
    # route. Absolutize against ``ui_url`` so the browser resolves the
    # 302 against the UI origin rather than the API host. ``ui_url`` is
    # empty in same-origin deployments, yielding a relative path the
    # browser resolves against the current host.
    path: str = (
        return_to
        if return_to is not None and _is_safe_return_to(return_to)
        else '/settings/connections'
    )
    ui_url = settings.get_server_config().ui_url
    target = f'{ui_url}{path}' if ui_url else path
    return fastapi.responses.RedirectResponse(target, status_code=302)


@me_identities_router.post('/{integration_id}/refresh')
async def refresh(
    integration_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('me:identities:manage'),
        ),
    ],
) -> dict[str, str]:
    """Force-refresh the actor's connection."""
    user = auth.require_user
    try:
        await flows.refresh_connection(
            db, integration_id=integration_id, actor_user_id=user.id
        )
    except errors.IdentityRequiredError as exc:
        raise fastapi.HTTPException(
            status_code=401,
            detail={
                'error': 'identity_required',
                'integration_id': exc.integration_id,
                'start_url': exc.start_url,
            },
        ) from exc
    except errors.IdentityRefreshFailed as exc:
        raise fastapi.HTTPException(status_code=502, detail=str(exc)) from exc
    return {'status': 'refreshed'}


@me_identities_router.delete('/{integration_id}')
async def disconnect(
    integration_id: str,
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(
            permissions.require_permission('me:identities:manage'),
        ),
    ],
) -> fastapi.responses.Response:
    """Revoke + delete the actor's connection for ``integration_id``.

    Returns ``204 No Content`` when both local and IdP revocation
    succeed (or no IdP call was needed). When the IdP-side revoke
    fails the local state is still recorded as revoked, but the
    response is ``200 OK`` with a JSON body so the UI can flag the
    partial state — the user needs to know the IdP still has live
    credentials and may need manual cleanup.
    """
    user = auth.require_user
    outcome = await flows.revoke_connection(
        db, integration_id=integration_id, actor_user_id=user.id
    )
    if not outcome['idp_revoked']:
        return fastapi.responses.JSONResponse(
            status_code=200,
            content={
                'detail': (
                    'Connection revoked locally, but the IdP rejected '
                    'the revocation call. The remote credentials may '
                    'still be valid until the IdP expires them.'
                ),
                'idp_error': outcome['idp_error'],
            },
        )
    return fastapi.Response(status_code=204)
