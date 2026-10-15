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
- on every route that is not classified as allowed: each mounted
  route (method and template) must be in :data:`ALLOWED_ROUTES`
  (:mod:`imbi.api.auth.agent_api_routes`) or refused above; a test
  fails on an unclassified route, so a new route needs a decision;
- for an organization that is not the token's: the ``org_slug`` (or,
  on the organization routes, ``slug``) path parameter must be the
  token's ``org_slug`` claim. The guard reads no database, so it adds
  no cost to other requests; a renamed organization refuses the token
  until the next heartbeat renews it.

The check uses the endpoint that the router matched, not the URL, so
an encoded path cannot slip past it.
"""

import typing

import fastapi
import jwt
from fastapi import routing

from imbi.api.auth.agent_api_routes import ALLOWED_ROUTES
from imbi.common.auth import core

#: Every route of these endpoint modules refuses the token.
REFUSED_MODULES = frozenset(
    {
        'imbi.api.endpoints.admin',
        'imbi.api.endpoints.admin_plugins',
        'imbi.api.endpoints.agent_task_harness',
        'imbi.api.endpoints.ai_providers',
        'imbi.api.endpoints.api_keys',
        'imbi.api.endpoints.auth',
        'imbi.api.endpoints.auth_providers',
        'imbi.api.endpoints.client_credentials',
        'imbi.api.endpoints.harness',
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


def refused(module: str, method: str) -> bool:
    """Whether the routes of ``module`` refuse the token for
    ``method``."""
    return module in REFUSED_MODULES or (
        module in READ_ONLY_MODULES and method not in _READS
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


def _forbidden(message: str) -> fastapi.HTTPException:
    return fastapi.HTTPException(
        status_code=403,
        detail={'error': 'agent_api_forbidden', 'message': message},
    )


def _bearer(request: fastapi.Request) -> str | None:
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    return token.strip() if scheme.lower() == 'bearer' else None


async def guard(request: fastapi.Request) -> None:
    """Refuse an agent API token where it must not work.

    Raises:
        401: The token is not valid or has expired.
        403: ``agent_api_forbidden``: a refused route, or another
            organization.

    """
    token = _bearer(request)
    if not token or not core.is_agent_api_token(token):
        return
    endpoint = request.scope.get('endpoint')
    module = str(getattr(endpoint, '__module__', ''))
    keys: dict[tuple[typing.Any, str], str] = getattr(
        request.app.state, 'agent_api_routes', {}
    )
    key = keys.get((endpoint, request.method))
    if refused(module, request.method) or key not in ALLOWED_ROUTES:
        raise _forbidden('An agent API token cannot use this route')
    try:
        claims = core.verify_agent_api_token(token)
    except jwt.InvalidTokenError as err:
        raise fastapi.HTTPException(
            status_code=401, detail='Invalid token'
        ) from err
    params = request.path_params
    slug = params.get('org_slug') or (
        params.get('slug')
        if module == 'imbi.api.endpoints.organizations'
        else None
    )
    if slug is not None and slug != claims['org_slug']:
        raise _forbidden(f'The token is not for organization {slug!r}')
