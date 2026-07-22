# imbi-plugin-aws

AWS provider for Imbi under Plugin Architecture v3. The package ships a
single `AWSPlugin` (slug `aws`) that backs an AWS Integration with three
capabilities from one credential blob.

## Capabilities

This package ships one `Plugin`, discovered by the imbi-common registry
via the `imbi_plugin_*` naming convention (module-level `PLUGIN`
attribute; no `imbi.plugins` entry points).

| Capability      | Contract                  | Backing service                   |
| --------------- | ------------------------- | --------------------------------- |
| `identity`      | `IdentityCapability`      | IAM Identity Center (device flow) |
| `logs`          | `LogsCapability`          | CloudWatch Logs Insights          |
| `configuration` | `ConfigurationCapability` | SSM Parameter Store               |

The `identity` capability federates each Imbi user into AWS via IAM
Identity Center (formerly AWS SSO) and mints short-lived STS credentials
per call. It is `project_scoped=False` (Integration-wide) and
`default_enabled=True` — for AWS, identity *is* the credential mechanism.
The `logs` and `configuration` capabilities set `requires_identity=True`
and consume those STS credentials transparently.

## Manifest shape

Integration-level (declared once, read from `ctx.integration_options`):

- `region` — default AWS region for every capability; a per-environment
  `AwsAccount.default_region` overrides it.
- `default_role_name` — IAM role assumed when a per-environment
  `AwsAccount` binding does not specify one.

Credentials (the only credential declaration, IAM IC auto-managed):
`client_id`, `client_secret`, `client_scopes`.

Capability options (read from `ctx.capability_options`):

- `identity`: `start_url` (required), `default_account_id`.
- `logs`: `log_group_names` (required), `base_filter`, `message_field`,
  `timestamp_field`, `level_field`, `poll_interval_ms`, `timeout_seconds`.
- `configuration`: `path_prefix` (required), `kms_key_id`,
  `timeout_seconds`.

## Identity consumption contract

When the `identity` capability's `materialize()` runs (host-side, before
a data capability's handler), it calls `GetRoleCredentials` against the
IAM IC Portal API and returns short-lived STS keys in
`IdentityCredentials.extra`:

```python
IdentityCredentials(
    access_token=<unchanged IAM IC token>,
    extra={
        'aws_access_key_id':     'AKIA...',
        'aws_secret_access_key': '...',
        'aws_session_token':     '...',
        'aws_region':            'us-east-1',
        'aws_account_id':        '111111111111',
    },
)
```

The host attaches this to `PluginContext.identity`; the `logs` and
`configuration` capabilities read the five well-known keys from
`ctx.identity.extra` via `aws_session.resolve_credentials()`. The account
and role are resolved per environment via
`(:Environment)-[:MAPS_TO]->(:AwsAccount)`, falling back to the
Integration-level `default_role_name` and `region`.

## License

BSD-3-Clause.
