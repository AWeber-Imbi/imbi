# imbi-plugin-aws Implementation Plan

An AWS provider for Imbi that ships **three** plugin entry points from a
single distribution:

- `aws-ssm` — `ConfigurationPlugin` backed by AWS Systems Manager
  Parameter Store.
- `aws-cloudwatch-logs` — `LogsPlugin` backed by CloudWatch Logs (Logs
  Insights).
- `aws-iam-ic` — `IdentityPlugin` backed by AWS IAM Identity Center
  (formerly AWS SSO). Per-user federated AWS identity. Provides STS
  temporary credentials to the two data plugins via the host's identity
  hydration path.

One package, one set of AWS dependencies (`aioboto3`), one shared
`aws_session.py` / `errors.py`. The identity plugin reuses the package's
existing credential and error machinery when its `materialize()` calls
STS.

## References

- Plugin authoring guide: `../imbi-common/docs/guides/plugins.md`
- Plugins API reference: `../imbi-common/docs/api/plugins.md`
- Base classes: `../imbi-common/src/imbi_common/plugins/base.py`
- Companion `LogsPlugin` example: `../imbi-plugin-logzio/`
- **Identity plugin design**: `../docs/identity-plugin-plan.md`
- **Identity plugin implementation plan**: `../docs/identity-plugin-implementation-plan.md`
- AWS APIs:
  - SSM Parameter Store:
    https://docs.aws.amazon.com/systems-manager/latest/APIReference/
  - CloudWatch Logs (Insights):
    https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/
  - IAM Identity Center OIDC + Portal:
    https://docs.aws.amazon.com/singlesignon/latest/OIDCAPIReference/
    https://docs.aws.amazon.com/singlesignon/latest/PortalAPIReference/

## Identity model alignment

The identity plugin design (`identity-plugin-plan.md`,
`identity-plugin-implementation-plan.md`) is the authoritative source
for how per-user AWS auth works. This plan uses its terminology and
contract; the relevant points:

- The **plugin contract** (in `imbi-common`) gains an `identity` plugin
  type with `IdentityPlugin` ABC. This package's `aws-iam-ic` entry
  point implements it.
- A `ConfigurationPlugin` / `LogsPlugin` assignment may carry an
  `identity_plugin_id` edge property. When set, the host runs
  `hydrate_identity()` before calling the plugin: it loads the actor's
  `IdentityConnection` for that identity plugin, refreshes if stale,
  calls `materialize()` (which for `aws-iam-ic` runs
  `GetRoleCredentials`), and attaches the result to
  `PluginContext.identity`. The `IdentityCredentials.extra` dict carries
  AWS temp creds under the well-known keys
  `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token`,
  `aws_region`, `aws_account_id`.
- When `identity_plugin_id` is **not** set on the assignment, the host
  falls through to `ServiceApplication.plugin_credentials` (the
  static-key path) — this is the **service-account fallback** for
  non-interactive callers (cron, automation).
- `aws-ssm` and `aws-cloudwatch-logs` therefore have a *single*
  credentials surface: a `dict[str, str]` of AWS keys. They do not know
  whether the keys are static (service account) or short-lived STS keys
  minted by `aws-iam-ic`. `aws_session.py` reads the same five well-
  known field names in either case.
- `AwsAccount` is a graph-resident node declared by **this package** via
  the manifest's `vertex_labels` (new field on `PluginManifest` in the
  identity plan). The `MAPS_TO` edge connects
  `Environment | Project | ProjectType | Organization` to `AwsAccount`.
  Account/role resolution at call time walks `MAPS_TO` from
  `PluginContext` according to the assignment's `account_selector`.

## Contract recap (from imbi-common)

- Per-request instance — no `self` state. Build clients inside each
  call.
- Manifests carry slug, options, credentials, plus (post-identity-plan)
  `vertex_labels`, `edge_labels`, `login_capable`, `requires_identity`,
  `default_scopes`, expanded `auth_type`/`plugin_type` literals.
- Errors raised should come from `imbi_common.plugins.errors` where
  applicable: `PluginCredentialsMissing`, `PluginTimeoutError`,
  `PluginUnavailableError`, `CursorExpiredError`. Identity-side errors
  (`IdentityRequiredError`, `IdentityRefreshFailed`) are host-side; the
  identity plugin raises domain-appropriate exceptions and the host
  maps them.
- Use `validate_template` / `expand_template` for any user-supplied
  template strings. Whitelist:
  `project_slug`, `org_slug`, `environment`, `project_id`.

## Async AWS client

`aioboto3`. A small shared `aws_session.py` builds a service client
from the credentials dict (and the assignment's `region`) so all three
plugins have identical auth handling.

## Auth — credential surface seen by the data plugins

Both `aws-ssm` and `aws-cloudwatch-logs` consume the same flat dict.
The host populates it from one of two sources, transparent to the
plugin:

| Key                     | Source A: static (no identity)                 | Source B: identity-hydrated                                    |
| ----------------------- | ---------------------------------------------- | -------------------------------------------------------------- |
| `aws_access_key_id`     | `ServiceApplication.plugin_credentials`        | `ctx.identity.extra['aws_access_key_id']` from `aws-iam-ic.materialize()` (STS) |
| `aws_secret_access_key` | `ServiceApplication.plugin_credentials`        | `ctx.identity.extra['aws_secret_access_key']`                  |
| `aws_session_token`     | `ServiceApplication.plugin_credentials` (opt.) | `ctx.identity.extra['aws_session_token']`                      |
| `aws_region`            | assignment option `region`                     | `ctx.identity.extra['aws_region']` (override) → assignment `region` |
| `aws_account_id`        | not set                                        | `ctx.identity.extra['aws_account_id']` (informational)         |

Validation in `aws_session.make_client()`:
- If `aws_access_key_id` and `aws_secret_access_key` are both absent →
  `PluginCredentialsMissing`. (When identity is required and
  hydration didn't run, the host has already raised
  `IdentityRequiredError` before we get here, so this only fires in the
  service-account path.)
- If exactly one of (id, secret) is present → `PluginCredentialsMissing`.

Plugin **options** carry `region` and any per-assignment knobs.

## Package layout

```
imbi-plugin-aws/
├── pyproject.toml
├── README.md
├── LICENSE
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── src/imbi_plugin_aws/
│   ├── __init__.py
│   ├── aws_session.py         # shared: build aioboto3 client from creds dict + region
│   ├── errors.py              # botocore -> imbi_common.plugins.errors mapping
│   ├── ssm.py                 # ConfigurationPlugin (aws-ssm)
│   ├── cloudwatch.py          # LogsPlugin (aws-cloudwatch-logs)
│   ├── query.py               # CloudWatch Logs Insights query builder + cursor codec
│   ├── identity.py            # IdentityPlugin (aws-iam-ic) — device flow, materialize
│   ├── models.py              # AwsAccount Pydantic model (declared in manifest)
│   ├── account_resolution.py  # MAPS_TO traversal -> chosen account+role
│   └── identity_hooks.py      # on_create/on_update/on_delete hooks for AwsAccount
└── tests/
    ├── test_aws_session.py
    ├── test_errors.py
    ├── test_ssm.py
    ├── test_cloudwatch.py
    ├── test_query.py
    ├── test_identity.py
    ├── test_account_resolution.py
    └── test_registry.py
```

`pyproject.toml` mirrors `../imbi-plugin-logzio/pyproject.toml`
(hatchling, ruff, py314, basedpyright strict, coverage ≥ 90). Three
entry points:

```toml
[project.entry-points."imbi.plugins"]
aws-ssm = "imbi_plugin_aws.ssm:SsmPlugin"
aws-cloudwatch-logs = "imbi_plugin_aws.cloudwatch:CloudWatchLogsPlugin"
aws-iam-ic = "imbi_plugin_aws.identity:AwsIamIcPlugin"
```

Dependencies: `imbi-common>=2.0`, `aioboto3>=13`, `pydantic>=2`. Dev:
`pytest`, `pytest-asyncio`, `moto[ssm,logs,sso,sso-oidc]>=5`,
`coverage[toml]`, `ruff`, `basedpyright`, `pre-commit`.

> **Testing note**: `moto` server-mode intercepts HTTP and works with
> `aioboto3` when the session's `endpoint_url` points at the moto
> server. Use server mode for SSM and CloudWatch Logs; for the IAM IC
> OIDC + Portal APIs, mock `aioboto3.Session.client` directly when moto
> coverage is incomplete (its `sso-oidc` support has historically lagged
> the AWS surface).

## Shared helper: `aws_session.py`

```python
async def make_client(
    service: typing.Literal['ssm', 'logs', 'sso', 'sso-oidc'],
    credentials: dict[str, str],
    *,
    region: str | None = None,
    timeout: float = 15.0,
) -> AsyncContextManager:
    ...
```

Behavior:
- Validate credentials (rules above) — raise `PluginCredentialsMissing`.
- Build an `aioboto3.Session` with the static keys (and session token if
  present).
- Resolve region: explicit `region` arg → `credentials['aws_region']`
  → raise `PluginCredentialsMissing`.
- Apply `botocore.config.Config(connect_timeout=...,
  read_timeout=..., retries={'max_attempts': 3, 'mode': 'standard'})`.
- Return the async context manager (caller `async with`s the client).

`make_client()` does **not** know whether the credentials originated
from static keys or STS. That decision is the host's, made in
`hydrate_identity()`.

`errors.py` maps `botocore.exceptions.ClientError` codes to imbi
exceptions (table reused by all three plugins).

---

## Plugin 1: `aws-ssm` (ConfigurationPlugin)

### Overview

Models a project's configuration as a path-scoped subtree of SSM
Parameter Store. Each project assignment carries a `path_prefix` (with
template variable expansion); plugin operations operate **only** within
that subtree to keep blast radius bounded.

### Manifest

```python
PluginManifest(
    slug='aws-ssm',
    name='AWS SSM Parameter Store',
    description='Read and write project configuration as SSM parameters.',
    plugin_type='configuration',
    api_version=1,
    cacheable=False,
    options=[
        PluginOption(
            name='region', label='AWS Region', type='string',
            required=True, choices=AWS_REGIONS),
        PluginOption(
            name='path_prefix', label='Parameter Path Prefix',
            type='string', required=True,
            description=(
                'Path prefix under which this project\'s parameters live. '
                'Supports ${project_slug}, ${org_slug}, ${environment}, '
                '${project_id}. Must start with /. '
                'Example: /imbi/${environment}/${project_slug}/')),
        PluginOption(
            name='kms_key_id', label='KMS Key ID',
            type='string', required=False,
            description=(
                'KMS key id/alias for SecureString writes. '
                'Defaults to alias/aws/ssm.')),
        PluginOption(
            name='timeout_seconds', label='Request Timeout',
            type='integer', default=15),
    ],
    credentials=[],   # see "Credentials" below
    data_types=[
        DataType(name='string', label='String'),
        DataType(name='string_list', label='String List'),
        DataType(name='secret', label='Secret', secret=True),
    ],
)
```

`AWS_REGIONS` is a hard-coded list pulled from
`botocore.session.Session().get_available_regions('ssm')` and frozen
in source (avoid network at import time).

### Credentials

The data plugins do not declare credential fields on their own
manifests. Two paths populate the credentials dict:

1. **Service-account path.** Operator stores AWS keys on the
   `ServiceApplication`; the host passes them to the plugin verbatim.
   Field names recognized: `aws_access_key_id`, `aws_secret_access_key`,
   `aws_session_token`. (Documented in the README; the host's
   `ServiceApplication` schema for "AWS" is operator-facing.)
2. **Identity path.** Assignment's `identity_plugin_id` points at
   `aws-iam-ic`. The host calls `aws-iam-ic.materialize()`, gets STS
   keys, and threads them through `PluginContext.identity.extra`. The
   host populates the credentials dict the plugin sees from
   `ctx.identity.extra` instead of `ServiceApplication.plugin_credentials`.

`aws-ssm` does not need to inspect `ctx.identity` — by the time
`get_values()` runs, the credentials dict is correct for whichever path
applied. (Per identity plan §6 "Plugin resolution path".)

### Region precedence

`region` option on the assignment wins for static keys. When identity
is in play, `ctx.identity.extra['aws_region']` (sourced from the
chosen `AwsAccount.default_region` or assignment override) takes
precedence. `aws_session.make_client()` honors this precedence.

### Data type mapping

| Imbi `data_type` | SSM `Type`     |
|------------------|----------------|
| `string`         | `String`       |
| `string_list`    | `StringList`   |
| `secret`         | `SecureString` |

When reading, derive Imbi `data_type` from SSM `Type`. Mark
`secret=True` only when SSM `Type == SecureString`. `string_list`
returns the raw CSV `Value` from SSM; users handle splitting at the
consuming end.

### `list_keys`

1. Validate template, expand `path_prefix`. Reject if missing leading
   `/` or just `/`.
2. Paginate `DescribeParameters` with
   `ParameterFilters=[{Key:'Path', Option:'Recursive', Values:[prefix]}]`.
3. For each parameter:
   - `key` = full name with `path_prefix` stripped (leading `/` removed).
   - `data_type` = reverse-mapped from `Type`.
   - `secret` = `Type == 'SecureString'`.
   - `last_modified` = `LastModifiedDate`.

### `get_values`

1. Validate + expand prefix.
2. If `keys is None`: paginate `DescribeParameters` (path filter) for
   names. Else: `[prefix.rstrip('/') + '/' + k.lstrip('/') for k in keys]`.
3. Fetch values:
   - **Subset path**: chunk into 10-name batches; call
     `GetParameters(Names=batch, WithDecryption=True)`. Ignore
     `InvalidParameters` (omit per contract).
   - **All path**: paginate `GetParametersByPath(Path=prefix,
     Recursive=True, WithDecryption=True)`.
4. Map → `ConfigKeyWithValue`. `StringList` value passes through as
   the raw CSV string.

### `set_value`

1. Validate + expand prefix. Reject keys containing `..` or starting
   with `/` (must be relative).
2. Full name = `f"{prefix.rstrip('/')}/{key}"`.
3. `Type` = forward-mapped from `value.data_type`. If
   `data_type == 'secret'`, pass `KeyId` = `kms_key_id` option (if set).
4. `PutParameter(Name=name, Value=value.value, Type=type,
   Overwrite=True, Tier='Standard')`.
5. `GetParameter(Name=name)` to fetch authoritative `LastModifiedDate`
   and return a `ConfigKey` reflecting persisted state.

### `delete_key`

1. Compute full name.
2. `DeleteParameter(Name=name)`. Catch `ParameterNotFound` → success
   (idempotent contract).

### Error mapping (SSM)

| botocore code | Imbi error |
|---|---|
| `ExpiredTokenException`, `UnrecognizedClientException`, `InvalidSignatureException`, `AccessDeniedException`, `UnauthorizedOperation` | `PluginCredentialsMissing` |
| `ThrottlingException`, `RequestLimitExceeded`, 5xx | `PluginUnavailableError` |
| `ParameterAlreadyExists` (non-overwrite paths) | `ValueError` |
| `ParameterNotFound` in `delete_key` | swallow (idempotent) |
| `ParameterNotFound` in `get_values` for a name | omit |
| `ValidationException` (bad name, bad type combo) | `ValueError` |
| `ReadTimeoutError`, `ConnectTimeoutError` | `PluginTimeoutError` |

---

## Plugin 2: `aws-cloudwatch-logs` (LogsPlugin)

### Overview

Searches CloudWatch Logs using **Logs Insights** (`StartQuery` →
`GetQueryResults` polling).

### Manifest

```python
PluginManifest(
    slug='aws-cloudwatch-logs',
    name='AWS CloudWatch Logs',
    description='Search CloudWatch Logs from the Imbi project logs tab.',
    plugin_type='logs',
    api_version=1,
    cacheable=False,
    options=[
        PluginOption(
            name='region', label='AWS Region', type='string',
            required=True, choices=AWS_REGIONS),
        PluginOption(
            name='log_group_names', label='Log Group Names',
            type='string', required=True,
            description=(
                'Comma-separated list of log group names. Supports '
                '${project_slug}, ${org_slug}, ${environment}, '
                '${project_id}. Up to 50 groups per query (Insights limit).')),
        PluginOption(
            name='base_filter', label='Base Filter Expression',
            type='string', required=False,
            description=(
                'Logs Insights expression (without the leading "filter") '
                'applied as an additional must clause. Supports the same '
                'template variables as Log Group Names.')),
        PluginOption(
            name='message_field', label='Message Field',
            type='string', default='@message'),
        PluginOption(
            name='timestamp_field', label='Timestamp Field',
            type='string', default='@timestamp'),
        PluginOption(
            name='level_field', label='Level Field',
            type='string', default='level'),
        PluginOption(
            name='poll_interval_ms', label='Poll Interval (ms)',
            type='integer', default=500),
        PluginOption(
            name='timeout_seconds', label='Query Timeout',
            type='integer', default=30),
    ],
    credentials=[],
)
```

Credentials path: identical to `aws-ssm` (see "Credentials" above).

### Filter translation (Insights syntax)

| Imbi op | Insights clause |
|---|---|
| `eq` | `filter <field> = "<value>"` |
| `ne` | `filter <field> != "<value>"` |
| `contains` | `filter <field> like "<value>"` (built-in escapes value) |
| `starts_with` | `filter <field> like /^<escaped>/` |
| `regex` | `filter <field> like /<value>/` |

Identifier rules: built-in fields use `@<name>` (e.g. `@message`,
`@timestamp`, `@logStream`, `@log`, `@requestId`, `@duration`); other
names are passed through (Insights treats unprefixed names as parsed
JSON fields).

### `search()`

1. Resolve credentials → `make_client('logs', ...)`.
2. Expand `log_group_names` template, split on `,`, trim. Empty after
   expansion → `ValueError`.
3. Build the Insights query:
   ```
   fields @timestamp, @message, @logStream
       | <base_filter clauses>
       | <user filters>
       | sort @timestamp desc
       | limit <min(query.limit, 10000)>
   ```
4. Cursor handling. **Decision: always re-issue the query with a
   narrowed `endTime`.**
   - **No cursor**: `StartQuery` with the assembled query, epoch-second
     `startTime` and `endTime`, `logGroupNames`.
   - **Cursor present**: decode cursor (codec below). On expired/invalid
     → `CursorExpiredError`. Cursor encodes the `last_seen_timestamp`
     and the query fingerprint; re-issue `StartQuery` with
     `endTime = last_seen_timestamp - 1ms`.
5. Poll `GetQueryResults(queryId)` every `poll_interval_ms` until
   `status == Complete`. Hard cap polling at `timeout_seconds`. On
   exceed: `StopQuery` then `PluginTimeoutError`. On
   `Failed`/`Cancelled`/`Timeout` from CloudWatch:
   `PluginUnavailableError` (carry the CloudWatch reason).
6. Map results → `LogEntry`.
7. Build `next_cursor` only when `len(entries) == size`. Cursor payload
   `{v:1, ts: <oldest_entry_iso>, fp: sha256(query_canonical)[:16]}`,
   base64-urlsafe encoded. `fp` binds the cursor to the same query.
8. Return `LogResult(entries, next_cursor, total=stats.recordsMatched)`.

### `schema()`

Curated baseline (Insights built-ins + conventional structured-log
fields):

```python
[
    {'name': '@timestamp',  'label': 'Timestamp',     'type': 'date',    'builtin': True},
    {'name': '@message',    'label': 'Message',       'type': 'text',    'builtin': True},
    {'name': '@logStream',  'label': 'Log Stream',    'type': 'keyword', 'builtin': True},
    {'name': '@log',        'label': 'Log Group',     'type': 'keyword', 'builtin': True},
    {'name': '@requestId',  'label': 'Request ID',    'type': 'keyword', 'builtin': True},
    {'name': 'level',       'label': 'Level',         'type': 'keyword'},
    {'name': 'logger',      'label': 'Logger',        'type': 'keyword'},
    {'name': 'service',     'label': 'Service',       'type': 'keyword'},
    {'name': 'env',         'label': 'Environment',   'type': 'keyword'},
    {'name': 'request_id',  'label': 'Request ID',    'type': 'keyword'},
]
```

Best-effort enrichment: `DescribeLogGroups` to surface a `log_groups`
discovery field. On any error, return baseline silently.

### Error mapping (CloudWatch Logs)

| botocore code | Imbi error |
|---|---|
| `AccessDeniedException`, `UnrecognizedClientException`, `ExpiredTokenException` | `PluginCredentialsMissing` |
| `ResourceNotFoundException` (log group missing) | `ValueError` |
| `MalformedQueryException`, `InvalidParameterException` | `ValueError` |
| `LimitExceededException`, `ThrottlingException`, 5xx | `PluginUnavailableError` |
| `ConnectTimeoutError`, `ReadTimeoutError`, polling cap exceeded | `PluginTimeoutError` |

---

## Plugin 3: `aws-iam-ic` (IdentityPlugin)

### Overview

OIDC-style federated identity backed by AWS IAM Identity Center (IAM IC,
formerly AWS SSO). Implements `IdentityPlugin` from the identity plan.
Each Imbi user authenticates once via the device-code flow; subsequent
calls to `aws-ssm` / `aws-cloudwatch-logs` use STS temporary
credentials minted via `GetRoleCredentials`.

### Manifest

```python
PluginManifest(
    slug='aws-iam-ic',
    name='AWS IAM Identity Center',
    description='Federated AWS access via IAM Identity Center.',
    plugin_type='identity',
    auth_type='aws-iam-ic',
    api_version=1,
    cacheable=False,
    login_capable=True,
    requires_identity=False,  # this IS the identity plugin
    default_scopes=['sso:account:access'],
    options=[
        PluginOption(
            name='start_url', label='IAM IC Start URL',
            type='string', required=True,
            description='e.g. https://example.awsapps.com/start'),
        PluginOption(
            name='region', label='IAM IC Region',
            type='string', required=True, choices=AWS_REGIONS,
            description='Region where IAM Identity Center is provisioned.'),
        PluginOption(
            name='default_account_id', label='Default Account',
            type='string', required=False,
            description=(
                'Optional default AWS account ID for non-interactive '
                'connect. When unset, the UI prompts for selection on '
                'first connect.')),
        PluginOption(
            name='default_role_name', label='Default Role',
            type='string', required=False,
            description='Optional default role to assume.'),
    ],
    credentials=[
        # The OIDC client_id/client_secret are minted by RegisterClient
        # at first use and cached on ServiceApplication.plugin_credentials
        # (encrypted). No operator-supplied credentials.
        CredentialField(
            name='client_id', label='Cached IAM IC Client ID',
            description='Auto-managed via RegisterClient.',
            required=False),
        CredentialField(
            name='client_secret', label='Cached IAM IC Client Secret',
            description='Auto-managed via RegisterClient.',
            required=False),
    ],
    vertex_labels=[
        PluginVertexLabel(
            name='AwsAccount',
            model_ref='imbi_plugin_aws.models:AwsAccount',
            indexes=[
                PluginIndex(fields=['account_id'], unique=True),
            ],
        ),
    ],
    edge_labels=[
        PluginEdgeLabel(
            name='MAPS_TO',
            from_labels=['Environment', 'Project',
                         'ProjectType', 'Organization'],
            to_labels=['AwsAccount'],
            properties={'tags': 'dict[str, str]'},
        ),
    ],
)
```

### `AwsAccount` model (`imbi_plugin_aws/models.py`)

```python
class AwsAccount(pydantic.BaseModel):
    id: str                                    # nano-ID, set by core
    account_id: typing.Annotated[
        str,
        pydantic.Field(pattern=r'^\d{12}$'),
    ]
    name: str
    default_role_name: str | None = None
    default_region: str | None = None
    tags: dict[str, str] = {}
```

`on_create(account)` hook (in `identity_hooks.py`) calls `ListAccounts`
on the operator's `ServiceApplication` connection (or the first active
admin's IAM IC connection if no service-account is configured) to
verify the account exists and auto-fill `name` if blank. On lookup
failure, persist with the operator-supplied `name` and log at WARNING.

### Authorization request (device flow)

The identity contract assumes redirect-then-callback. `aws-iam-ic`
extends `AuthorizationRequest` with the `polling: PollingDescriptor`
field added by the identity plan §"Risks" — OIDC and GitHub leave it
null; AWS uses it.

Flow:
1. **`RegisterClient`** (one-time per `ServiceApplication`). On first
   call, register an OIDC client with `clientName='imbi'`,
   `clientType='public'`. Cache the returned `clientId` /
   `clientSecret` / `clientSecretExpiresAt` on the
   `ServiceApplication.plugin_credentials` (via the host's encryption
   layer). Re-register when the cached pair is within 7 days of expiry.
2. **`StartDeviceAuthorization`** with the cached client + the
   assignment's `start_url`. Returns `verificationUriComplete`,
   `userCode`, `deviceCode`, `interval`, `expiresIn`.
3. Return:
   ```python
   AuthorizationRequest(
       authorization_url=verificationUriComplete,
       state='<JWT carrying device_code, client_id, client_secret_ref,
              region, intent, return_to>',
       polling=PollingDescriptor(
           interval_seconds=interval,
           expires_in_seconds=expiresIn,
           user_code=userCode,
       ),
   )
   ```

The Imbi UI renders the `userCode` and polls
`/me/identities/{plugin_id}/poll` (host-side endpoint introduced by the
identity plan). The host calls a new
`IdentityPlugin.poll(ctx, credentials, state)` method to drive the
poll. `aws-iam-ic.poll()` calls `CreateToken(grant_type=device_code,
deviceCode=...)`. AWS returns `authorization_pending` while the user is
still authenticating; on success it returns the access token + (when
configured) refresh token.

> **Contract note.** The identity plan flags `polling: PollingDescriptor`
> as the minimum surface for non-redirect flows but does not yet add a
> `poll()` method on the ABC. **This plugin requires that addition.**
> Tracked in §"Required additions to the identity plan" below.

### `exchange_code(...)`

For redirect-callback identities (`oidc`, `github`), this is the OAuth
code-for-token call. AWS IAM IC uses the polling path instead, so
`exchange_code` is implemented as a thin wrapper around the same
`CreateToken(grant_type=device_code)` AWS call, using the `code`
argument as the `deviceCode`. Hosts that use the polling path call
`poll()`; hosts that bridge polling into the standard exchange call
`exchange_code` with `code=deviceCode`. Both produce
`tuple[IdentityProfile, IdentityCredentials]`.

After token grant:
1. `ListAccounts(accessToken)` and `ListAccountRoles` populate the
   user's available accounts/roles.
2. Choose the active `(account_id, role_name)`:
   - If `default_account_id` + `default_role_name` are set on the
     manifest options and the user has access → use them.
   - Else surface the choice list to the UI; the UI picks and includes
     the selection in the connection's metadata. (`IdentityCredentials`
     does *not* hold the access token plus account choice; the
     `IdentityConnection` row's metadata does.)
3. **Do not** call `GetRoleCredentials` here. STS creds are short-lived
   (1h max); minting them at connect time wastes them. `materialize()`
   does it lazily per call.

`IdentityProfile` populated from IAM IC userinfo:
- `subject` = `accessToken`'s sub claim if available, else the IAM IC
  user ID returned by `GetSsoSession`.
- `email` / `name` from IAM IC user metadata when accessible.

`IdentityCredentials` returned holds the IdP access token (the IAM IC
token, *not* AWS STS keys yet) plus refresh token if granted. The
chosen account/role lives in `extra` so `materialize()` can read it:
```python
IdentityCredentials(
    access_token=<iam-ic-access-token>,
    token_type='Bearer',
    expires_at=<token-expiry>,
    refresh_token=<refresh-or-None>,
    scopes=[...],
    extra={
        'aws_account_id': '111111111111',
        'aws_role_name': 'PowerUserAccess',
        'aws_region': '<resolved at materialize time>',
    },
)
```

### `refresh(...)`

If the IAM IC token grants a refresh token:
`CreateToken(grant_type=refresh_token, refreshToken=...)`. Else: raise
`IdentityRefreshFailed` and let the host mark the connection
`status='expired'` so the user re-runs the device flow. (Per identity
plan §"Background refresh".)

### `revoke(...)`

IAM IC OIDC does not expose a public revoke endpoint. Default no-op
implementation; the host still deletes the local
`IdentityConnection`.

### `materialize(...)` — the AWS-specific exchange

Called per dependent-plugin call (after host-side hot-path cache check).
Steps:
1. Load `(account_id, role_name)` from `connection.extra` (set at
   connect time). If missing, attempt resolution via
   `account_resolution.resolve_account(graph, ctx, assignment_options)`
   and use that account's `default_role_name`.
2. Resolve region: `ctx.assignment_options.region` →
   `account.default_region` → manifest `region`.
3. `GetRoleCredentials(roleName, accountId, accessToken)` against the
   IAM IC Portal API in the chosen region.
4. Return:
   ```python
   IdentityCredentials(
       access_token=connection.access_token,  # unchanged
       token_type='Bearer',
       expires_at=<min(connection.expires_at, sts_expiry)>,
       refresh_token=connection.refresh_token,
       scopes=connection.scopes,
       extra={
           'aws_access_key_id': sts['accessKeyId'],
           'aws_secret_access_key': sts['secretAccessKey'],
           'aws_session_token': sts['sessionToken'],
           'aws_region': region,
           'aws_account_id': account_id,
       },
   )
   ```

`materialize()` is the only place STS keys appear in the plugin. The
host snapshots `IdentityCredentials.extra` into the credentials dict
the data plugins receive.

### Account resolution (`account_resolution.py`)

```python
async def resolve_account(
    graph: Graph,
    ctx: PluginContext,
    options: dict[str, typing.Any],
) -> AwsAccount:
    selector = options.get('account_selector', [
        'project', 'environment', 'project_type', 'organization'])
    tag_filters = options.get('tag_filters', {})
    for anchor in selector:
        node = _node_for_anchor(graph, ctx, anchor)
        if node is None:
            continue
        candidates = await graph.match(
            f'({anchor})-[:MAPS_TO]->(:AwsAccount)',
            from_id=node.id)
        for cand in candidates:
            if all(cand.tags.get(k) == v for k, v in tag_filters.items()):
                return cand
    raise AccountNotResolvedError(selector=selector, ctx=ctx)
```

`AccountNotResolvedError` maps to HTTP 412 in the host with a body
listing the selector that was tried. (Identity plan §9 specifies the
resolver lives "inside the same package" — this is it.)

### Error mapping (IAM IC OIDC + Portal)

| botocore code / state | Imbi error |
|---|---|
| `UnauthorizedClientException`, `InvalidClientException` | `PluginCredentialsMissing` (re-register prompted by host) |
| `ExpiredTokenException` on `GetRoleCredentials` | `IdentityRefreshFailed` (host marks expired) |
| `AccessDeniedException` on `ListAccounts` / `GetRoleCredentials` | `PluginUnavailableError` (user lacks access — surface the user-facing message) |
| `AuthorizationPendingException` from `CreateToken` | sentinel; host's poll loop continues |
| `SlowDownException` from `CreateToken` | bump poll interval, continue |
| `ExpiredTokenException` from `CreateToken` | `CursorExpiredError`-equivalent for device flow; host re-issues `start` |
| `ThrottlingException`, 5xx | `PluginUnavailableError` |
| `ConnectTimeoutError`, `ReadTimeoutError` | `PluginTimeoutError` |

---

## RDS-specific CloudWatch Logs evaluation

**Conclusion: no special handling required in v1.** RDS publishes its
own logs (PostgreSQL `postgresql.log`, MySQL `error/slowquery/general`,
Aurora `audit`) to CloudWatch under predictable group names:

```
/aws/rds/instance/<db-instance-id>/postgresql
/aws/rds/instance/<db-instance-id>/error
/aws/rds/cluster/<cluster-id>/postgresql
```

The same `aws-cloudwatch-logs` plugin handles RDS logs once the
project's assignment is configured with the right log group(s).
Insights queries up to 50 log groups in a single call, so a single
search across every log group for one instance is fine.

Caveats documented in the README rather than implemented:

1. **Multi-line log events.** PostgreSQL stack traces span multiple
   lines; CloudWatch ingests each line as a separate event. Out-of-
   scope server-side reassembly.
2. **Unstructured format.** Postgres lines look like
   `2026-04-15 12:34:56 UTC:10.0.0.1(5432):user@db:[12345]:LOG: ...`.
   Insights `parse` can extract fields per query; we don't hardcode
   profiles. Tracked as a v2 follow-up.
3. **Slow-query log volume.** Insights' server-side limits handle
   high-cardinality slow-query groups better than `FilterLogEvents`.
4. **Audit logs (`/aws/rds/cluster/<id>/audit`)** are CSV. Same caveat
   on field naming; v2.
5. **RDS exports must be enabled.** Anything not enabled isn't in
   CloudWatch at all; the plugin can't reach those via
   `DownloadDBLogFilePortion` (different AWS surface, out of scope).

Ship the generic `aws-cloudwatch-logs` plugin; add an "RDS log groups"
example to the README; defer parse-profile work.

---

## Tests

Mirror the structure used in `imbi-plugin-logzio`:

- `test_aws_session.py` — credential validation matrix; static and
  identity-sourced creds shape; region precedence.
- `test_errors.py` — exhaustive botocore code → imbi error mapping
  (covers SSM, Logs, IAM IC OIDC).
- `test_query.py` — Insights query string assembly; filter operator
  table; cursor encode/decode round-trip; fp mismatch raises
  `CursorExpiredError`.
- `test_ssm.py` — moto-server-backed CRUD; secret/string-list/string
  round trips; idempotent delete; subset vs all fetch paths; data-type
  forward+reverse mapping. Two suites: one with static creds in dict,
  one with identity-extra-shaped creds, asserting plugin code is
  oblivious to source.
- `test_cloudwatch.py` — mocked StartQuery → poll → GetQueryResults
  cycle; timeout cancels via StopQuery; cursor narrows endTime on
  follow-up; full vs partial page → next_cursor presence; static vs
  identity-sourced creds.
- `test_identity.py` — `RegisterClient` cache lifecycle;
  `StartDeviceAuthorization` → `poll()` happy path and
  `AuthorizationPendingException` retry; `exchange_code` parity with
  `poll()`; `materialize()` calls `GetRoleCredentials` with the chosen
  account/role; `refresh()` paths; `IdentityCredentials.__repr__` is
  redacted (cross-check against the contract test in imbi-common).
- `test_account_resolution.py` — selector ordering; tag filter
  matching; `AccountNotResolvedError` raised with selector context.
- `test_registry.py` — three entry points discoverable; manifests
  validate; classes are correct subclasses; vertex/edge label
  declarations parse and `model_ref` resolves.
- Coverage target ≥ 90%.

## CI / tooling

Identical to logzio:
- GitHub Actions: lint (ruff), type-check (basedpyright), tests with
  coverage on Python 3.14.
- Pre-commit: ruff format + lint, end-of-file-fixer, trailing-whitespace.
- `uv` for dependency management; `uv.lock` committed.
- `[tool.uv.sources]` editable path to `../imbi-common`.

## Build order (suggested)

1. Scaffold `pyproject.toml`, ruff/pre-commit/CI.
2. `aws_session.py` + `errors.py` with full unit tests.
3. `ssm.py` + tests against moto. (Smaller surface; gets the auth path
   exercised end-to-end first against the static-key path.)
4. `query.py` (Insights builder + cursor codec) with full unit tests.
5. `cloudwatch.py` + tests with mocked Insights polling.
6. `models.py` + `account_resolution.py` + tests.
7. `identity.py` (`AwsIamIcPlugin`) + `identity_hooks.py` + tests.
8. `test_registry.py` for all three entry points.
9. README: configuration walkthrough; static vs IAM IC auth setup;
   RDS log-group recipe; IAM policy examples (least-privilege per
   plugin); IAM IC `RegisterClient` operator setup.

## Required additions to the identity plan

The identity plan calls these out as risks; this plugin needs them
landed before it can be implemented end-to-end. Flag to the identity
plan author:

1. **`IdentityPlugin.poll()` method.** The identity plan's
   `AuthorizationRequest.polling: PollingDescriptor` is acknowledged but
   the contract has no `poll()` method on the ABC. AWS device flow is
   the first concrete consumer. Proposed signature:

   ```python
   class IdentityPlugin(abc.ABC):
       async def poll(
           self,
           ctx: PluginContext,
           credentials: dict[str, str],
           state: str,
       ) -> tuple[IdentityProfile, IdentityCredentials] | None:
           """Drive the polling step of a device-code flow.

           Returns (profile, credentials) when the user has completed
           authorization, or ``None`` to indicate the host should keep
           polling. Raises :class:`IdentityFlowExpiredError` when the
           device code has expired.
           """
           return None  # default: not a polling flow
   ```

2. **Account-selection metadata on `IdentityConnection`.** Per identity
   plan §9, the chosen `(account_id, role_name)` is stored in "the
   connection's metadata". Confirm the metadata field shape — easiest
   path is reusing `IdentityConnection.scopes` semantics with a new
   `extra: dict[str, str]` JSON field on the vlabel (additive,
   not breaking).

3. **`PluginManifest.vertex_labels` / `edge_labels` schema.** Already
   in the identity implementation plan §2, but confirms this plugin's
   manifest is the first concrete user. The collision-detection step
   (§4 of that plan) needs to be live before this package is loaded
   into a real environment.

4. **Service-account fallback semantics.** When
   `assignment.identity_plugin_id` is unset, the host falls through to
   `ServiceApplication.plugin_credentials`. Confirm that `aws-ssm` and
   `aws-cloudwatch-logs` should expose **no** `credentials` fields on
   their manifests (the AWS keys are read from the
   `ServiceApplication`'s opaque blob whose schema is operator-facing,
   not plugin-declared) — or whether the data plugins should still
   declare `aws_access_key_id` / `aws_secret_access_key` /
   `aws_session_token` so the admin UI can collect them. Plan
   currently assumes the former (no declared credentials on the data
   plugins) since the identity plan treats credentials as an
   operator/host-managed concept; if the host expects per-plugin
   credential declarations even for static-only paths, the data
   plugins' manifests grow three optional `CredentialField`s.

## Open follow-ups (not blocking v1)

- `parse`-profile system for RDS / nginx / Apache log formats.
- Per-assignment `kms_key_id` override for SSM secrets.
- Multi-region per assignment (currently one region per assignment;
  multi-region = multiple assignments).
- GitHub App installation tokens (out of scope; see identity plan).
- CloudWatch Insights `stats` (recordsMatched / bytesScanned) surfacing
  through a future `LogResult` extension.

---

## Resolved decisions (locked)

These were open in the previous draft; the identity plan resolves
them:

1. **Three entry points in one distribution.** `aws-ssm`,
   `aws-cloudwatch-logs`, `aws-iam-ic`. (Identity plan §9 "First-Party
   Plugins".)
2. **Auth model.** Per-user federated identity via `aws-iam-ic`; static
   keys on `ServiceApplication` as the service-account fallback.
   `role_arn` / `external_id` on the data plugins is **dropped** — the
   STS dance lives entirely inside `aws-iam-ic.materialize()`.
   (Identity plan §"Goals", "First-Party Plugins".)
3. **Async client.** `aioboto3`. Locked.
4. **SSM `string_list`.** Raw CSV pass-through. Locked.
5. **CloudWatch search backend.** Logs Insights. Locked.
6. **RDS handling.** Defer parse-profiles to v2; document log-group
   recipe in README.
7. **Region scoping.** One region per assignment.
8. **Service-account fallback (was open #4).** Lands as the static-key
   path; no `identity_plugin_id` on the assignment → host uses
   `ServiceApplication.plugin_credentials`. The data plugins are
   identical regardless of source.
