# MCP Toolset Policy

Shared policy for building AI toolsets from the Imbi OpenAPI spec.

## Overview

The Imbi AI services (`imbi-mcp`, `imbi-assistant`, and future bots) turn
the Imbi API's `/openapi.json` into a toolset via
`fastmcp.FastMCP.from_openapi`. This module centralises *which*
operations are kept out of those toolsets so the decision lives in one
place instead of being copied into each consumer:

- **`EXCLUDED_ROUTE_MAPS`** — a static path/method denylist (auth, MFA,
  status, thumbnails) passed as `route_maps`.
- **`exclude_non_ai_tools`** — a `route_map_fn` that honours the
  `x-imbi-ai-tool: false` extension imbi-api stamps on sensitive
  operations (e.g. project Configuration / SSM Parameter Store).
- **`copy_permissions_to_meta`** — an `mcp_component_fn` that records the
  `x-imbi-permission` extension on each generated component's public
  `meta`.
- **`PermissionFilterMiddleware`** — narrows `tools/list` per caller to
  the operations that caller has permission for. Requires
  `copy_permissions_to_meta`; advisory only, and fails open.

Keeping the *which* in imbi-api (it stamps the extension on tagged
operations) and the *how to honour it* here means hiding a future endpoint
from every AI service is just a matter of tagging it in imbi-api.

Requires the `mcp` extra:

```
imbi-common[mcp]
```

## Usage

The two pieces compose — pass the static maps as `route_maps` (alongside
any consumer-specific maps) and the hook as `route_map_fn`:

```python
import fastmcp
import httpx

from imbi.common import mcp

client = httpx.AsyncClient(base_url="http://localhost:8000")
server = fastmcp.FastMCP.from_openapi(
    openapi_spec=spec,
    client=client,
    name="Imbi",
    route_maps=list(mcp.EXCLUDED_ROUTE_MAPS),
    route_map_fn=mcp.exclude_non_ai_tools,
)
```

A consumer with its own classification rules prepends the shared maps to
its own:

```python
server = fastmcp.FastMCP.from_openapi(
    openapi_spec=spec,
    client=client,
    route_maps=[*mcp.EXCLUDED_ROUTE_MAPS, *MY_ROUTE_MAPS],
    route_map_fn=mcp.exclude_non_ai_tools,
)
```

Note that every operation becomes a **tool** by default, reads included.
Classifying `GET`s as MCP resources or resource templates hides them from
clients that only consume `tools/*`, so consumers should not do it.

To filter each caller's toolset down to what they can actually invoke,
add the `mcp_component_fn` and the middleware:

```python
server = fastmcp.FastMCP.from_openapi(
    openapi_spec=spec,
    client=client,
    route_maps=list(mcp.EXCLUDED_ROUTE_MAPS),
    route_map_fn=mcp.exclude_non_ai_tools,
    mcp_component_fn=mcp.copy_permissions_to_meta,
)
server.add_middleware(mcp.PermissionFilterMiddleware(client))
```

Both parts are required: without `copy_permissions_to_meta` no tool
carries permission metadata, so the middleware has nothing to filter on
and returns every tool. The `client` must forward the calling
principal's credentials, or every caller is filtered against one
identity.

`exclude_non_ai_tools` is backward compatible: when the extension is
absent it returns `None` and changes nothing, so a consumer can adopt it
before or after imbi-api ships the flag. `copy_permissions_to_meta` is
likewise a no-op on operations with no `x-imbi-permission`.

## API Reference

::: imbi.common.mcp.AI_TOOL_EXTENSION

::: imbi.common.mcp.EXCLUDED_ROUTE_MAPS

::: imbi.common.mcp.exclude_non_ai_tools

::: imbi.common.mcp.PERMISSION_EXTENSION

::: imbi.common.mcp.PERMISSION_META_KEY

::: imbi.common.mcp.copy_permissions_to_meta

::: imbi.common.mcp.required_permissions

::: imbi.common.mcp.PermissionFilterMiddleware
