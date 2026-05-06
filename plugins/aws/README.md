# imbi-plugin-aws

AWS provider for the Imbi project logs and configuration tabs.

## Plugins shipped

This package ships (or will ship) three entry points from one
distribution:

| Slug                   | Type            | Status   |
| ---------------------- | --------------- | -------- |
| `aws-iam-ic`           | `identity`      | ✅ shipped |
| `aws-ssm`              | `configuration` | planned  |
| `aws-cloudwatch-logs`  | `logs`          | planned  |

The identity plugin federates each Imbi user into AWS via IAM Identity
Center (formerly AWS SSO) and mints short-lived STS credentials per
call.  The data plugins (when shipped) consume those credentials
transparently — see the contract below.

## Identity consumption contract for the data plugins

When a project's `(:Project)-[:USES_PLUGIN]->(:Plugin)` edge or
project-type fallback names this package's `aws-iam-ic` plugin via the
`identity_plugin_id` edge property, the host-side
`hydrate_identity()` helper runs `aws-iam-ic.materialize()` *before*
calling the data plugin's handler.  `materialize()` calls
`GetRoleCredentials` against the IAM IC Portal API and returns
short-lived STS keys in `IdentityCredentials.extra`:

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

The host attaches this to `PluginContext.identity` and the data plugins
read it from there.  Concretely, when `aws-ssm` (or
`aws-cloudwatch-logs`) is invoked:

```python
async def list_keys(self, ctx, credentials):
    if ctx.identity is not None:
        # IAM IC path: credentials dict is empty (no operator-supplied
        # static keys); read STS from ctx.identity.extra.
        aws_creds = ctx.identity.extra
    else:
        # Static-key path: ServiceApplication.plugin_credentials carries
        # access_key_id / secret_access_key / session_token.
        aws_creds = credentials
    session = aiobotocore.session.get_session()
    client = session.create_client(
        'ssm',
        region_name=aws_creds['aws_region'],
        aws_access_key_id=aws_creds['aws_access_key_id'],
        aws_secret_access_key=aws_creds['aws_secret_access_key'],
        aws_session_token=aws_creds.get('aws_session_token'),
    )
    ...
```

The data plugin doesn't know whether the caller is federated (via
`aws-iam-ic`) or running as a service principal (legacy
`ServiceApplication.plugin_credentials`).  Same five well-known keys,
sourced differently.

`requires_identity=true` on a future logs/configuration manifest would
make the federated path mandatory; today both plugins fall back to the
service-principal credentials when no `ctx.identity` is set.

## License

BSD-3-Clause.
