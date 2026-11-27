"""Where an agent API token works in imbi-api (harness plan P7).

A runner relays an agent's Imbi tool calls with an agent API token
(:func:`imbi.api.harness.tokens.mint_agent_api_token`). The shared
authentication accepts it as the agent's service account, with its
roles (H28). :func:`guard`, an application dependency, runs for every
route and refuses it:

- on the routes that change authentication, tokens, service accounts,
  roles, secrets, or the harness: every route of the endpoint modules
  in :data:`REFUSED_MODULES`, and the writes of the modules in
  :data:`READ_ONLY_MODULES` (users and agents make memberships and
  service accounts);
- on the writes that change the rules that govern agents, or that
  create or change what holds or sends credentials or data outside
  Imbi (:data:`~imbi.api.auth.agent_api_routes.REFUSED_ROUTES`);
- on every route that is not classified as allowed: each mounted
  route (method and template) must be in :data:`ALLOWED_ROUTES`
  (:mod:`imbi.api.auth.agent_api_routes`) or refused above; a test
  fails on an unclassified route, so a new route needs a decision;
- for an organization that is not the token's: the ``org_slug`` (or,
  on the organization routes, ``slug``) path parameter, or an ``org``
  query parameter, must be the token's ``org_slug`` claim. A
  ``project_id`` path parameter must name a project of that
  organization (404 otherwise): some project routes do not check that
  the project is in the path's organization. An allowed route with no
  organization parameter must be in :data:`GLOBAL_SAFE`, with the
  reason that it gives no data of another organization.

A user token with an ``org_slug`` claim (imbi-slackbot mints one per
Slack workspace organization, #1027) gets the same organization and
project checks, on every route: a route with no organization in its
path must be in :data:`GLOBAL_SAFE`. The other route rules apply only
to agent API tokens; the user's own permissions still apply.

Only these two token kinds read the database (the project check);
other requests pay nothing. A renamed organization refuses the token
until a new one is minted.

The check uses the endpoint that the router matched, not the URL, so
an encoded path cannot slip past it.
"""

import typing

import fastapi
import jwt
from fastapi import routing

from imbi.api.auth.agent_api_routes import ALLOWED_ROUTES, REFUSED_ROUTES
from imbi.common import graph, lifespan
from imbi.common.auth import core, permissions

#: Every route of these endpoint modules refuses the token.
REFUSED_MODULES = frozenset(
    {
        'imbi.api.endpoints.admin',
        'imbi.api.endpoints.admin_plugins',
        'imbi.api.endpoints.ticket_harness',
        'imbi.api.endpoints.ai_providers',
        'imbi.api.endpoints.api_keys',
        'imbi.api.endpoints.auth',
        'imbi.api.endpoints.auth_providers',
        'imbi.api.endpoints.client_credentials',
        'imbi.api.endpoints.harness',
        # The connector configuration holds the ClickHouse password.
        'imbi.api.endpoints.iggy_connectors',
        'imbi.api.endpoints.local_auth',
        'imbi.api.endpoints.mcp_servers',
        'imbi.api.endpoints.mfa',
        'imbi.api.endpoints.oauth_metadata',
        'imbi.api.endpoints.roles',
        'imbi.api.endpoints.sa_api_keys',
        'imbi.api.endpoints.secret_broker',
        'imbi.api.endpoints.service_accounts',
        'imbi.api.identity.endpoints',
    }
)
#: Only the reads of these modules accept the token.
READ_ONLY_MODULES = frozenset(
    {'imbi.api.endpoints.agents', 'imbi.api.endpoints.users'}
)
_READS = frozenset({'GET', 'HEAD', 'OPTIONS'})

#: The allowed routes with no organization in the path, and why each
#: gives no data of another organization.
GLOBAL_SAFE: dict[str, str] = {
    'GET /blueprints/': 'global schema configuration',
    'GET /blueprints/{type}': 'global schema configuration',
    'GET /blueprints/{type}/{slug}': 'global schema configuration',
    'GET /cves/{cve_id}': 'a public CVE List record: no organization data',
    'GET /scoring/policies/': 'global scoring configuration',
    'GET /scoring/policies/{slug}': 'global scoring configuration',
    'GET /plugins/{slug}/manifest': 'a plugin manifest: no organization data',
    'GET /operations-log/plugin-templates': 'plugin templates: no entries',
    'GET /status': 'service status',
    'GET /users/me': 'the caller itself',
    'GET /users/me/permissions': 'the caller itself',
    'POST /operations-log/': (
        'the handler refuses an agent entry for a project of another '
        'organization (require_own_project)'
    ),
    'GET /scores/history-by-team': (
        'the required org query parameter is checked'
    ),
    'GET /scores/history-feed': (
        'the required org query parameter is checked'
    ),
    'GET /scores/monthly-improvement': (
        'the required org query parameter is checked'
    ),
    'GET /scores/rollup': 'the required org query parameter is checked',
}

_PROJECT_IN_ORG: typing.LiteralString = """
MATCH (p:Project {{id: {project_id}}})
      -[:OWNED_BY]->(:Team)
      -[:BELONGS_TO]->(:Organization {{slug: {org_slug}}})
RETURN p.id AS id
LIMIT 1
"""
_PROJECT_IN_ORG_ID: typing.LiteralString = """
MATCH (p:Project {{id: {project_id}}})
      -[:OWNED_BY]->(:Team)
      -[:BELONGS_TO]->(:Organization {{id: {org_id}}})
RETURN p.id AS id
LIMIT 1
"""


def refused(module: str, method: str, key: str | None = None) -> bool:
    """Whether a route refuses the token: its module for ``method``,
    or its ``"METHOD /template"`` key."""
    return (
        module in REFUSED_MODULES
        or (module in READ_ONLY_MODULES and method not in _READS)
        or key in REFUSED_ROUTES
    )


def route_keys(
    app: fastapi.FastAPI, prefix: str
) -> dict[tuple[typing.Any, str], str]:
    """``(endpoint, method)`` to ``"METHOD /template"`` (the template
    without the API prefix) for every mounted API route."""
    keys: dict[tuple[typing.Any, str], str] = {}
    for route in app.routes:
        if isinstance(route, routing.APIRoute):
            template = route.path.removeprefix(prefix) or '/'
            for method in route.methods:
                keys[(route.endpoint, method)] = f'{method} {template}'
    return keys


def index(app: fastapi.FastAPI, prefix: str) -> None:
    """Keep the route keys on the app, after every router is
    included."""
    app.state.agent_api_routes = route_keys(app, prefix)


def _forbidden(
    message: str, error: str = 'agent_api_forbidden'
) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=403, detail={'error': error, 'message': message}
    )


def _user_token_org(token: str) -> str | None:
    """The ``org_slug`` claim of a valid user access token, if any. An
    invalid token (or an ``ik_`` API key) gives ``None``: the
    authentication decides."""
    try:
        claims = core.verify_token(token)
    except jwt.InvalidTokenError:
        return None
    if claims.get('type') != 'access':
        return None
    return claims.get('org_slug') or None


def _bearer(request: fastapi.Request) -> str | None:
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    return token.strip() if scheme.lower() == 'bearer' else None


async def graph_for(request: fastapi.Request) -> graph.Graph | None:
    """The graph of the app lifespan, or ``None`` in an app without one
    (unit tests). Only an agent API token request reads it; with
    ``None``, its project check fails closed."""
    try:
        context = lifespan.get_lifespan(request)
        return context.get_state(graph.graph_lifespan)
    except Exception:  # noqa: BLE001 - no lifespan: no graph
        return None


async def _project_in(
    db: graph.Graph | None, query: typing.LiteralString, args: dict[str, str]
) -> None:
    if db is None:
        raise fastapi.HTTPException(
            status_code=503, detail='The project check is not available'
        )
    if not await db.execute(query, args, ['id']):
        raise fastapi.HTTPException(
            status_code=404, detail='Project not found'
        )


async def require_own_project(
    db: graph.Graph | None,
    auth: permissions.AuthContext,
    project_id: str | None,
) -> None:
    """For an agent API token, or a user token of one organization:
    ``project_id`` must name a project of the token's organization.
    For a handler whose project is in the body. Other callers pass.

    Raises:
        403: An entry without a project.
        404: The project is not in the token's organization.

    """
    if not auth.organization_slug:
        return
    if not project_id:
        raise _forbidden(
            'This token needs a project here',
            'agent_api_forbidden'
            if auth.auth_method == 'agent_api'
            else 'organization_forbidden',
        )
    # An agent API token carries the organization ID: use it, so that a
    # slug that another organization takes after a rename does not
    # match. A user token carries only the slug.
    if auth.organization_id:
        await _project_in(
            db,
            _PROJECT_IN_ORG_ID,
            {'project_id': project_id, 'org_id': auth.organization_id},
        )
    else:
        await _project_in(
            db,
            _PROJECT_IN_ORG,
            {'project_id': project_id, 'org_slug': auth.organization_slug},
        )


def _org_scoped(key: str | None) -> bool:
    """Whether the route names the organization in its path."""
    return key is not None and (
        '{org_slug}' in key or ' /organizations/{slug}' in key
    )


async def _require_org(
    request: fastapi.Request,
    db: graph.Graph | None,
    module: str,
    org_slug: str,
    error: str,
) -> None:
    """The path and ``org`` query organization must be ``org_slug``,
    and a path project must be in it."""
    params = request.path_params
    for slug in (
        params.get('org_slug'),
        params.get('slug')
        if module == 'imbi.api.endpoints.organizations'
        else None,
        request.query_params.get('org'),
    ):
        if slug is not None and slug != org_slug:
            raise _forbidden(
                f'The token is not for organization {slug!r}', error
            )
    if 'project_id' in params:
        await _project_in(
            db,
            _PROJECT_IN_ORG,
            {'project_id': str(params['project_id']), 'org_slug': org_slug},
        )


async def guard(
    request: fastapi.Request,
    db: typing.Annotated[graph.Graph | None, fastapi.Depends(graph_for)],
) -> None:
    """Refuse an agent API token where it must not work, and a user
    token of one organization outside that organization.

    Raises:
        401: The agent API token is not valid or has expired.
        403: ``agent_api_forbidden``: a refused route, or another
            organization. ``organization_forbidden``: a user token of
            one organization on another organization, or on a route
            with no organization that is not in :data:`GLOBAL_SAFE`.
        404: The path's project is not in the token's organization.

    """
    token = _bearer(request)
    if not token:
        return
    endpoint = request.scope.get('endpoint')
    module = str(getattr(endpoint, '__module__', ''))
    keys: dict[tuple[typing.Any, str], str] = getattr(
        request.app.state, 'agent_api_routes', {}
    )
    key = keys.get((endpoint, request.method))
    org_slug: str | None
    if core.is_agent_api_token(token):
        error = 'agent_api_forbidden'
        if refused(module, request.method, key) or key not in ALLOWED_ROUTES:
            raise _forbidden('An agent API token cannot use this route')
        try:
            org_slug = str(core.verify_agent_api_token(token)['org_slug'])
        except jwt.InvalidTokenError as err:
            raise fastapi.HTTPException(
                status_code=401, detail='Invalid token'
            ) from err
    else:
        error = 'organization_forbidden'
        org_slug = _user_token_org(token)
        if org_slug is None:
            return
    # The tests keep every allowed agent route that has no organization
    # in GLOBAL_SAFE, so this refuses only user tokens.
    if not _org_scoped(key) and key not in GLOBAL_SAFE:
        raise _forbidden(
            f'This token works only in organization {org_slug!r}', error
        )
    await _require_org(request, db, module, org_slug, error)
