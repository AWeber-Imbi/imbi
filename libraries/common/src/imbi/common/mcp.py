"""Shared policy for building AI toolsets from the Imbi OpenAPI spec.

``imbi-mcp`` and ``imbi-assistant`` (and any future AI service) build
their toolsets by turning the Imbi API's ``/openapi.json`` into tools via
:meth:`fastmcp.FastMCP.from_openapi`. This module centralises *which*
operations are kept out of those toolsets so the policy lives in one place
rather than being copied into each consumer:

* :func:`excluded_route_maps` -- a path/method denylist (auth, MFA,
  status, thumbnails) passed as ``route_maps``.
* :func:`exclude_non_ai_tools` -- a ``route_map_fn`` that honours the
  ``x-imbi-ai-tool: false`` extension imbi-api stamps on sensitive
  operations (e.g. project Configuration / SSM Parameter Store).
* :class:`PermissionFilterMiddleware` -- middleware that narrows
  ``tools/list`` per caller, dropping operations whose required
  permissions (``x-imbi-permission``) the caller does not hold.
* :class:`AccessLogContextMiddleware` -- middleware that names the
  invoked tool in the HTTP access log line, which otherwise records
  every call as an indistinguishable ``POST /mcp``.

The API mounts its routers under a deployment-specific path prefix (the
path component of ``IMBI_API_URL``, e.g. ``/api``), which the spec's
paths carry but a client's ``base_url`` does not. Everything here that
names a path therefore derives that prefix from the spec via
:func:`mount_prefix`.

These compose. Pass ``excluded_route_maps(spec)`` (optionally alongside
a consumer's own maps) as ``route_maps`` and :func:`exclude_non_ai_tools`
as ``route_map_fn``. :class:`PermissionFilterMiddleware` additionally
requires :func:`copy_permissions_to_meta` as ``mcp_component_fn`` --
that is what records each operation's permissions on the tool, so
without it the middleware finds nothing to filter on and every tool is
returned::

    import fastmcp
    from imbi.common import mcp

    server = fastmcp.FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        route_maps=mcp.excluded_route_maps(spec),
        route_map_fn=mcp.exclude_non_ai_tools,
        mcp_component_fn=mcp.copy_permissions_to_meta,
    )
    server.add_middleware(mcp.PermissionFilterMiddleware(client, spec))

Requires the ``mcp`` extra (``imbi-common[mcp]``).

"""

from __future__ import annotations

import collections
import hashlib
import logging
import re
import time
import typing

import fastmcp.server.middleware
import httpx
from fastmcp.server.dependencies import get_http_headers, get_http_request
from fastmcp.server.providers.openapi import MCPType, RouteMap

from imbi.common import access_log

if typing.TYPE_CHECKING:
    import collections.abc

    from fastmcp.tools import Tool
    from fastmcp.utilities.components import FastMCPComponent
    from fastmcp.utilities.openapi import HTTPRoute

LOGGER = logging.getLogger(__name__)

#: OpenAPI operation extension imbi-api stamps on endpoints that must not
#: be exposed to AI. Its presence (set to ``False``) hides the operation
#: regardless of path or method -- the API owns which endpoints are
#: sensitive (e.g. project Configuration / SSM Parameter Store).
AI_TOOL_EXTENSION = 'x-imbi-ai-tool'

#: OpenAPI operation extension imbi-api stamps with the list of
#: permissions an operation requires (``['admin']`` for admin-only
#: endpoints). Permission checks are FastAPI dependencies and so are
#: otherwise invisible in the spec.
#: :class:`PermissionFilterMiddleware` reads it to filter a caller's
#: toolset down to what that caller can actually invoke.
PERMISSION_EXTENSION = 'x-imbi-permission'

#: Spec path whose presence reveals the API's mount prefix. Every
#: domain router is mounted under the prefix, so any known-prefixed
#: operation works; this one is used because
#: :class:`PermissionFilterMiddleware` has to call it anyway.
PROFILE_PATH = '/users/me'


def mount_prefix(spec: collections.abc.Mapping[str, typing.Any]) -> str:
    """Return the path prefix the API's routers are mounted under.

    imbi-api mounts every domain router under the path component of
    ``IMBI_API_URL`` (e.g. ``/api``), so the spec describes
    ``/api/users/me`` while an internal client's ``base_url`` is just
    ``http://imbi-api:8000``. Anything that names a path by hand has to
    add the prefix back, and the spec is the only place it appears.

    Returns:
        The prefix (``''`` when the API is mounted at the root),
        derived from the spec path ending in :data:`PROFILE_PATH`.

    Raises:
        ValueError: When the spec does not contain exactly one path
            ending in :data:`PROFILE_PATH`. This fails *closed*:
            assuming the root would unanchor
            :func:`excluded_route_maps`, re-exposing auth and MFA
            operations as tools, and would point
            :class:`PermissionFilterMiddleware` at a profile URL that
            does not exist.

    """
    paths: collections.abc.Iterable[str] = spec.get('paths') or {}
    matches = [path for path in paths if path.endswith(PROFILE_PATH)]
    if len(matches) != 1:
        raise ValueError(
            f'Cannot determine the API mount prefix: expected exactly '
            f'one spec path ending in {PROFILE_PATH}, found '
            f'{len(matches)}'
        )
    return matches[0].removesuffix(PROFILE_PATH)


def excluded_route_maps(
    spec: collections.abc.Mapping[str, typing.Any],
) -> list[RouteMap]:
    """Endpoints that must never become AI tools regardless of tagging.

    Covers authentication, MFA, the status probe, and image thumbnails.
    The patterns are anchored at the spec's mount prefix so they still
    match on a deployment served under one (e.g. ``/api/auth/login``).

    Args:
        spec: The OpenAPI spec the toolset is built from.

    """
    prefix = re.escape(mount_prefix(spec))
    return [
        RouteMap(pattern=rf'^{prefix}/auth/', mcp_type=MCPType.EXCLUDE),
        RouteMap(pattern=rf'^{prefix}/mfa/', mcp_type=MCPType.EXCLUDE),
        RouteMap(pattern=rf'^{prefix}/status/?$', mcp_type=MCPType.EXCLUDE),
        RouteMap(pattern=r'.*/thumbnail/?$', mcp_type=MCPType.EXCLUDE),
    ]


def exclude_non_ai_tools(
    route: HTTPRoute, _mcp_type: MCPType
) -> MCPType | None:
    """Exclude operations imbi-api flagged as off-limits for AI.

    Intended to be passed as ``route_map_fn`` to
    :meth:`fastmcp.FastMCP.from_openapi`.

    Args:
        route: The OpenAPI route fastmcp is classifying.
        _mcp_type: The component type fastmcp would otherwise assign;
            unused, since the flag overrides any classification.

    Returns:
        :attr:`MCPType.EXCLUDE` when the operation carries
        ``x-imbi-ai-tool: false``, else ``None`` to leave the existing
        route-map decision unchanged. The check is identity-against
        ``False`` so an explicit ``x-imbi-ai-tool: true`` (or the absence
        of the extension) keeps the operation.

    """
    if route.extensions.get(AI_TOOL_EXTENSION) is False:
        return MCPType.EXCLUDE
    return None


#: Key under which :func:`copy_permissions_to_meta` records an
#: operation's required permissions on the generated component's public
#: ``meta`` dict.
PERMISSION_META_KEY = 'imbi_permission'


def copy_permissions_to_meta(
    route: HTTPRoute, component: FastMCPComponent
) -> None:
    """Copy an operation's required permissions onto the component.

    Intended to be passed as ``mcp_component_fn`` to
    :meth:`fastmcp.FastMCP.from_openapi`. The route carries
    :data:`PERMISSION_EXTENSION` from the spec, but the generated
    component only keeps its route privately; recording the value in
    the public ``meta`` dict at build time lets
    :class:`PermissionFilterMiddleware` read it later without reaching
    into fastmcp internals.
    """
    permissions = route.extensions.get(PERMISSION_EXTENSION)
    if not permissions:
        return
    component.meta = (component.meta or {}) | {
        PERMISSION_META_KEY: permissions
    }


def required_permissions(tool: Tool) -> list[str]:
    """Return the permissions an operation-backed tool enforces.

    Reads what :func:`copy_permissions_to_meta` recorded. Tools built
    without that ``mcp_component_fn``, or whose operation has no
    permission dependency, return an empty list.
    """
    meta = getattr(tool, 'meta', None) or {}
    value = meta.get(PERMISSION_META_KEY)
    return value if isinstance(value, list) else []


def _remember_api_key_owner(
    credential: str | None, profile: collections.abc.Mapping[str, typing.Any]
) -> None:
    """Label an API key's owner in the HTTP access log.

    :mod:`imbi.common.access_log` runs synchronously in the response
    path, so it can only render the opaque ``ik_<id>`` it parses from
    the ``Authorization`` header unless something resolves the owner
    for it. The API does that during its own authentication; an MCP
    server never authenticates the key itself, but it does fetch the
    caller's profile to filter tools, so the owner is free here.

    Only user-owned keys get a label: service-account keys receive
    ``403`` from :data:`PROFILE_PATH` (it requires a human user), so
    their log lines keep showing the key id.
    """
    if not credential or not credential.lower().startswith('bearer ik_'):
        return
    token = credential.split(' ', 1)[1]
    parts = token.split('_', 2)
    email = profile.get('email')
    if len(parts) == 3 and isinstance(email, str):
        access_log.remember_api_key_principal(f'ik_{parts[1]}', email)


class PermissionFilterMiddleware(fastmcp.server.middleware.Middleware):
    """Hide tools the calling principal cannot invoke.

    ``tools/list`` is filtered down to operations whose required
    permissions (see :data:`PERMISSION_EXTENSION`) the caller actually
    holds, so an agent is not offered hundreds of tools that can only
    ever return ``403``. The caller's effective permissions come from
    the API's :data:`PROFILE_PATH`, which reports ``is_admin`` and the
    ``permissions`` list; admins are never filtered, matching the
    API's own admin bypass. That path is resolved against the spec's
    :func:`mount_prefix`, since the client's ``base_url`` does not
    carry the prefix the API is mounted under.

    Requires the server to have been built with
    :func:`copy_permissions_to_meta` as its ``mcp_component_fn``.
    Without it no tool carries permission metadata, so there is nothing
    to filter on and every tool is returned.

    This is **advisory only** -- the API remains the sole enforcement
    point. Filtering therefore fails *open*: if the profile lookup
    fails, or the request carries no credentials, the unfiltered list
    is returned rather than an empty toolset. A caller who invokes a
    hidden tool anyway still gets a ``403`` from the API.

    Resolved profiles are cached per credential for
    :data:`CACHE_TTL_SECONDS`, since clients re-list tools on reconnect
    and on capability changes rather than only once per session. The
    cache is bounded and keyed on a hash of the credential so the raw
    token is never held in memory -- the same tradeoff the API makes
    for API-key auth. Permission changes therefore take effect within
    the TTL.
    """

    #: Sentinel permission meaning "admin only" -- no non-admin
    #: principal can hold it, so such tools are always filtered out.
    ADMIN_PERMISSION = 'admin'

    #: How long a resolved profile stays usable. Short, so revocations
    #: and role changes surface quickly.
    CACHE_TTL_SECONDS = 60

    #: Upper bound on cached profiles, evicted least-recently-used.
    CACHE_MAX_ENTRIES = 1024

    def __init__(
        self,
        client: httpx.AsyncClient,
        spec: collections.abc.Mapping[str, typing.Any],
    ) -> None:
        """Store the API client used to resolve the caller's profile.

        Args:
            client: Client bound to the Imbi API that forwards the
                calling principal's credentials -- the same client used
                to build the toolset. Its auth must be per-caller, or
                every caller would be filtered against one identity.
            spec: The OpenAPI spec the toolset was built from, used to
                resolve the profile path against the API's mount prefix.
        """
        self._client = client
        self._profile_path = f'{mount_prefix(spec)}{PROFILE_PATH}'
        self._cache: collections.OrderedDict[
            str, tuple[float, tuple[bool, set[str]]]
        ] = collections.OrderedDict()

    def _cache_lookup(self, key: str) -> tuple[bool, set[str]] | None:
        """Return a cached profile if present and unexpired."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires, profile = entry
        if time.monotonic() > expires:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return profile

    def _cache_store(self, key: str, profile: tuple[bool, set[str]]) -> None:
        """Store a profile, evicting the least-recently-used entry."""
        while len(self._cache) >= self.CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)
        self._cache[key] = (
            time.monotonic() + self.CACHE_TTL_SECONDS,
            profile,
        )

    async def _caller_permissions(self) -> tuple[bool, set[str]] | None:
        """Return ``(is_admin, permissions)``, or ``None`` if unknown.

        Cached per credential; see the class docstring for the tradeoff.
        Callers without a credential are not cached, since they would
        all collide on one key.
        """
        credential = get_http_headers(include={'authorization'}).get(
            'authorization'
        )
        key = (
            hashlib.sha256(credential.encode('utf-8')).hexdigest()
            if credential
            else ''
        )
        if key:
            cached = self._cache_lookup(key)
            if cached is not None:
                return cached
        try:
            response = await self._client.get(self._profile_path)
            response.raise_for_status()
            profile = response.json()
        except (httpx.HTTPError, ValueError):
            LOGGER.warning(
                'Could not resolve caller permissions; '
                'returning the unfiltered tool list',
                exc_info=True,
            )
            return None
        if not isinstance(profile, dict):
            LOGGER.warning(
                'Unexpected /users/me payload of type %s; '
                'returning the unfiltered tool list',
                type(profile).__name__,
            )
            return None
        _remember_api_key_owner(credential, profile)
        permissions = profile.get('permissions') or []
        resolved = (
            bool(profile.get('is_admin')),
            {item for item in permissions if isinstance(item, str)},
        )
        if key:
            self._cache_store(key, resolved)
        return resolved

    def _is_invocable(self, required: list[str], granted: set[str]) -> bool:
        """Return whether a non-admin caller may invoke the operation.

        :data:`ADMIN_PERMISSION` is a sentinel rather than a real grant,
        so it is rejected outright -- admin callers never reach here,
        and a caller who happens to hold a permission literally named
        ``admin`` must not thereby gain admin-only tools.
        """
        if self.ADMIN_PERMISSION in required:
            return False
        return set(required).issubset(granted)

    async def on_list_tools(
        self,
        context: fastmcp.server.middleware.MiddlewareContext[typing.Any],
        call_next: typing.Any,
    ) -> collections.abc.Sequence[Tool]:
        """Filter ``tools/list`` to what the caller may invoke."""
        tools: collections.abc.Sequence[Tool] = await call_next(context)
        gated = [(tool, required_permissions(tool)) for tool in tools]
        if not any(required for _, required in gated):
            return tools
        resolved = await self._caller_permissions()
        if resolved is None:
            return tools
        is_admin, granted = resolved
        if is_admin:
            return tools
        kept = [
            tool
            for tool, required in gated
            if self._is_invocable(required, granted)
        ]
        LOGGER.debug(
            'Filtered tool list from %d to %d for caller permissions',
            len(tools),
            len(kept),
        )
        return kept


class AccessLogContextMiddleware(fastmcp.server.middleware.Middleware):
    """Name the invoked tool in the HTTP access log line.

    Every MCP call arrives as ``POST /mcp``, so the access log alone
    cannot tell a project lookup from a deployment write. This records
    the tool name in the request state
    :mod:`imbi.common.access_log` reads, rendering it as
    ``... 200 (tool:list_projects)``.

    A no-op under the stdio transport, where there is no HTTP request
    (and no access log) to annotate.
    """

    async def on_call_tool(
        self,
        context: fastmcp.server.middleware.MiddlewareContext[typing.Any],
        call_next: typing.Any,
    ) -> typing.Any:
        """Record the tool name, then run the call."""
        try:
            request = get_http_request()
        except RuntimeError:
            return await call_next(context)
        existing = getattr(request.state, 'imbi_common_access_log', None) or {}
        request.state.imbi_common_access_log = {
            **existing,
            'tool': context.message.name,
        }
        return await call_next(context)
