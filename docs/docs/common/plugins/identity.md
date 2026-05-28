# Identity Plugins

`IdentityPlugin` is the abstract base for plugins that authenticate a
specific user to a third-party system via OAuth 2.0, OIDC, or an
OIDC-shaped device-code flow (e.g. AWS IAM Identity Center). Declare
`plugin_type='identity'` in the manifest, along with the matching
`auth_type` (`'oauth2'`, `'oidc'`, or `'aws-iam-ic'`).

Identity plugins exist so that other plugins — typically
[deployment](deployment.md) plugins — can act *as the human user*
rather than as a shared service principal. After a user links their
account, the host materializes their credentials into
`PluginContext.identity` for the data plugin's calls.

See [Authoring Plugins](index.md) for the manifest, context, credential
resolution, and error conventions shared by every plugin.

```python
from imbi_common.plugins import (
    AuthorizationRequest,
    IdentityCredentials,
    IdentityPlugin,
    IdentityProfile,
    PluginContext,
)


class GitHubIdentityPlugin(IdentityPlugin):
    manifest = manifest  # plugin_type='identity', auth_type='oauth2'

    async def authorization_request(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        redirect_uri: str,
        scopes: list[str] | None = None,
    ) -> AuthorizationRequest:
        ...

    async def exchange_code(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> tuple[IdentityProfile, IdentityCredentials]:
        ...

    async def refresh(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        refresh_token: str,
    ) -> IdentityCredentials:
        ...
```

## Method contracts

- **`authorization_request`** — return what the host needs to start the
  flow: the `authorization_url` to redirect the browser to, an opaque
  `state`, and (for PKCE) a `code_verifier`. For non-redirect device
  flows return a `PollingDescriptor` in `polling`; the UI then polls
  `/me/identities/{plugin_id}/poll` and surfaces the `user_code`. If the
  plugin mints credentials on the fly (e.g. OIDC dynamic-client
  registration), return them in `registered_credentials` so the host
  persists them for the matching `exchange_code` / `refresh` calls.
- **`exchange_code`** — exchange the authorization code (or completed
  device authorization) for a normalized `IdentityProfile` and the
  `IdentityCredentials` to store. While an out-of-band step is still
  pending, raise
  [`IdentityAuthorizationPending`][imbi_common.plugins.IdentityAuthorizationPending];
  once the device code has expired, raise
  [`IdentityAuthorizationExpired`][imbi_common.plugins.IdentityAuthorizationExpired].
- **`refresh`** — exchange a stored refresh token for fresh
  `IdentityCredentials`.
- **`revoke`** — optional best-effort revocation; the default is a no-op
  for IdPs without a revoke endpoint.
- **`materialize`** — optional hook for plugins that must exchange the
  IdP token for a backend-specific credential at call time (AWS IAM IC
  overrides this to call `GetRoleCredentials` and return STS keys in
  `IdentityCredentials.extra`). The default returns the stored
  connection unchanged.

## Manifest fields

- **`auth_type`** must be `'oauth2'`, `'oidc'`, or `'aws-iam-ic'` so the
  host resolves credentials and renders the connect flow correctly.
- **`login_capable`** marks an identity plugin usable as a sign-in
  provider for Imbi itself.
- **`requires_identity`** is set by *data* plugins (deployment, etc.) to
  signal they need a linked identity before they can act.
- **`default_scopes`** are the scopes requested when none are supplied
  to `authorization_request`.
- **`widget_text`** is the body copy shown on the dashboard
  "unconnected integration" widget prompting the user to link.
- **`vertex_labels`** typically declare an `IdentityConnection` vlabel so
  the host can persist per-user connections (see
  [Plugin-declared Graph Schema](index.md#plugin-declared-graph-schema)).

## API reference

::: imbi_common.plugins.IdentityPlugin

::: imbi_common.plugins.IdentityProfile

::: imbi_common.plugins.IdentityCredentials

::: imbi_common.plugins.AuthorizationRequest

::: imbi_common.plugins.PollingDescriptor
