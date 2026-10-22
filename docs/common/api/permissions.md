# Permissions

The `imbi.common.auth.permissions` module authenticates a request and
checks its permissions. `imbi-api`, `imbi-assistant`, `imbi-scheduler`
and `imbi-workflows` use it. The module reads the graph, so the service
must have the graph pool in its lifespan.

## Authenticate a request

`get_current_user` is a FastAPI dependency. It reads the
`Authorization: Bearer <token>` header and returns an `AuthContext`. It
accepts three kinds of token:

| Token | Format | `auth_method` |
|---|---|---|
| API key | `ik_<key_id>_<secret>` | `api_key` |
| Agent API token | Detected by `core.is_agent_api_token` | `agent_api` |
| JWT access token | Any other token | `jwt` |

A missing or bad token gives `401`.

For an API key, the permissions are the permissions of the key owner,
limited to the key's scopes. An empty scope list means no limit. The
module caches a successful API-key result for 60 seconds, for at most
1024 keys. A cache hit skips the secret check and the permission queries,
but it still reads the key from the graph. Thus a revoked, rotated,
deleted, or expired key fails at once. A change to the owner's roles
applies within 60 seconds. Call `clear_api_key_cache()` to remove the
cached results at once.

A client-credentials JWT (`auth_method` `client_credentials`) follows the
same rule: when the token has a `scope` claim, the permissions are
limited to those scopes.

A service refuses agent API tokens until it calls
`accept_agent_api_tokens()`. Only `imbi-api` calls it. An agent API
token works in one organization only (`AuthContext.organization_id`).

`get_current_user_cookie_fallback` also reads the token from the
`imbi_access_token` cookie when the header is missing. Use it only for
endpoints that a browser loads as a subresource, such as `<img src>`.

## Require a permission

`require_permission(name)` returns a dependency that authenticates the
request and then checks for the permission. An admin user passes every
check. A service account never passes a check that it does not have the
permission for. A missing permission gives `403`.

```python
import typing

import fastapi

from imbi.common import graph
from imbi.common.auth import permissions

router = fastapi.APIRouter()


@router.get('/blueprints')
async def list_blueprints(
    db: graph.Pool,
    auth: typing.Annotated[
        permissions.AuthContext,
        fastapi.Depends(permissions.require_permission('blueprint:read')),
    ],
) -> list[dict]:
    ...
```

Set `allow_cookie=True` to accept the cookie, as
`get_current_user_cookie_fallback` does.

The dependency sets the `imbi_permission` attribute on the function that
it returns. The API OpenAPI generator reads this attribute and adds
`x-imbi-permission` to each operation.

## Permission sources

`load_principal_permissions` collects the permissions of a user or a
service account from its organization memberships. It follows the
`INHERITS_FROM` and `GRANTS` relationships of the roles. With
`org_slug`, it uses only the role in that organization.

`validate_scopes` raises `400` when a scope is not a seeded permission
name. Call it before you store the scopes of a new API key.

For the list of permissions and the roles that have them, see
[Roles and permissions](../../admin/roles-and-permissions.md).

## Auth settings

The module reads the `Auth` settings through a provider. The default is
`settings.get_auth_settings`. A service that extends `settings.Auth`
must call `set_auth_settings_provider()` with its own getter. If it does
not, the process has two settings objects. When `IMBI_AUTH_JWT_SECRET`
is not set, each object makes its own JWT secret, and tokens made with
one secret fail verification with the other.

## API Reference

::: imbi.common.auth.permissions.get_current_user

::: imbi.common.auth.permissions.get_current_user_cookie_fallback

::: imbi.common.auth.permissions.require_permission

::: imbi.common.auth.permissions.AuthContext

::: imbi.common.auth.permissions.IdentityInfo

::: imbi.common.auth.permissions.authenticate_jwt

::: imbi.common.auth.permissions.authenticate_api_key

::: imbi.common.auth.permissions.authenticate_agent_api

::: imbi.common.auth.permissions.accept_agent_api_tokens

::: imbi.common.auth.permissions.clear_api_key_cache

::: imbi.common.auth.permissions.load_principal_permissions

::: imbi.common.auth.permissions.load_all_permission_names

::: imbi.common.auth.permissions.validate_scopes

::: imbi.common.auth.permissions.set_auth_settings_provider

::: imbi.common.auth.permissions.auth_settings
