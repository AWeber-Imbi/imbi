# Identity Capability

`IdentityCapability` is the contract base for a capability that
authenticates a specific user to a remote via OAuth 2.0, OIDC, or an
OIDC-shaped device-code flow (e.g. AWS IAM Identity Center). Bind it with
a `Capability(kind='identity', handler=...)` and set the plugin
manifest's `auth_type` to match (`'oauth2'`, `'oidc'`, or
`'aws-iam-ic'`).

Identity capabilities exist so that other capabilities — typically
[deployment](deployment.md) — can act *as the human user* rather than as
a shared service principal. After a user links their account, the host
materializes their credentials into `PluginContext.identity` for a
capability that sets `requires_identity=True`. Identity is
Integration-wide, so its capability is typically declared with
`project_scoped=False`.

Surfaces: **api**.

See [Authoring Plugins](index.md) for the manifest, capabilities,
context, credential decryption, and error conventions shared by every
plugin.

```python
from imbi_common.plugins import (
    AuthorizationRequest,
    IdentityCapability,
    IdentityCredentials,
    IdentityProfile,
    PluginContext,
)


class GitHubIdentity(IdentityCapability):
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
  `/me/identities/{integration_id}/poll` and surfaces the `user_code`. If
  the capability mints credentials on the fly (e.g. OIDC dynamic-client
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
- **`materialize`** — optional hook for capabilities that must exchange
  the IdP token for a backend-specific credential at call time (AWS IAM
  IC overrides this to call `GetRoleCredentials` and return STS keys in
  `IdentityCredentials.extra`). The default returns the stored
  connection unchanged.

## Hints

- **`login_capable`** — the identity capability is usable as a sign-in
  provider for Imbi itself.
- **`default_scopes`** — the scopes requested when none are supplied to
  `authorization_request`.
- **`widget_text`** — body copy for the dashboard "unconnected
  integration" widget prompting the user to link.
- **`cacheable`** — the host may cache reads from this capability.

The plugin manifest's `vertex_labels` typically declare an
`IdentityConnection` vlabel so the host can persist per-user connections
(see [Plugin-declared Graph Schema](index.md#plugin-declared-graph-schema)).

## API reference

::: imbi_common.plugins.IdentityCapability

::: imbi_common.plugins.IdentityProfile

::: imbi_common.plugins.IdentityCredentials

::: imbi_common.plugins.AuthorizationRequest

::: imbi_common.plugins.PollingDescriptor
