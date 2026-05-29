"""Shared policy for building AI toolsets from the Imbi OpenAPI spec.

``imbi-mcp`` and ``imbi-assistant`` (and any future AI service) build
their toolsets by turning the Imbi API's ``/openapi.json`` into tools via
:meth:`fastmcp.FastMCP.from_openapi`. This module centralises *which*
operations are kept out of those toolsets so the policy lives in one place
rather than being copied into each consumer:

* :data:`EXCLUDED_ROUTE_MAPS` -- a static path/method denylist (auth, MFA,
  status, thumbnails) passed as ``route_maps``.
* :func:`exclude_non_ai_tools` -- a ``route_map_fn`` that honours the
  ``x-imbi-ai-tool: false`` extension imbi-api stamps on sensitive
  operations (e.g. project Configuration / SSM Parameter Store).

The two compose: pass ``EXCLUDED_ROUTE_MAPS`` (optionally alongside a
consumer's own maps) as ``route_maps`` and :func:`exclude_non_ai_tools`
as ``route_map_fn``::

    import fastmcp
    from imbi_common import mcp

    server = fastmcp.FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        route_maps=list(mcp.EXCLUDED_ROUTE_MAPS),
        route_map_fn=mcp.exclude_non_ai_tools,
    )

Requires the ``mcp`` extra (``imbi-common[mcp]``).

"""

from __future__ import annotations

import typing

from fastmcp.server.providers.openapi import MCPType, RouteMap

if typing.TYPE_CHECKING:
    from fastmcp.utilities.openapi import HTTPRoute

#: OpenAPI operation extension imbi-api stamps on endpoints that must not
#: be exposed to AI. Its presence (set to ``False``) hides the operation
#: regardless of path or method -- the API owns which endpoints are
#: sensitive (e.g. project Configuration / SSM Parameter Store).
AI_TOOL_EXTENSION = 'x-imbi-ai-tool'

#: Endpoints that should never become AI tools regardless of tagging --
#: authentication, MFA, the status probe, and image thumbnails.
EXCLUDED_ROUTE_MAPS: list[RouteMap] = [
    RouteMap(pattern=r'^/auth/', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'^/mfa/', mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r'^/status/?$', mcp_type=MCPType.EXCLUDE),
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
