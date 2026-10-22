# AWS

The `aws` plugin connects Imbi to Amazon Web Services. One integration
gives three capabilities that share one credential mechanism:

- Each user connects through AWS IAM Identity Center with a device code.
- The project **Logs** tab searches CloudWatch Logs Insights.
- The project **Configuration** tab reads and writes SSM Parameter Store.

The integration stores no static AWS keys. For each call, Imbi gets
short-lived STS credentials for the user from IAM Identity Center.

## Capabilities

| Capability | Label | Default | Scope |
|---|---|---|---|
| `identity` | AWS IAM Identity Center | On | Organization-wide. Each user connects at **Settings > Connections** |
| `logs` | AWS CloudWatch Logs | On | Project-scoped. Needs the user identity. Supports the histogram |
| `configuration` | AWS SSM Parameter Store | On | Project-scoped. Needs the user identity |

## Configuration

### Options

| Option | Label | Required | Meaning |
|---|---|---|---|
| `region` | AWS Region | Yes | The default region for IAM Identity Center, CloudWatch, and SSM. The `default_region` of a mapped AWS account overrides it |
| `default_role_name` | Default IAM Role | No | The IAM Identity Center role (permission set) to use when the mapped AWS account has no role. Supports the [template variables](#template-variables) |
| `project_type_path_map` | Project Type Path Overrides | No | A map from a project type slug to the text that `${project_type_slug}` gives, for example `apis` to `api`. A slug with no entry stays the same |

### Identity capability options

| Option | Label | Required | Meaning |
|---|---|---|---|
| `start_url` | IAM IC Start URL | Yes | The AWS access portal URL, for example `https://example.awsapps.com/start` |
| `default_account_id` | Default AWS Account ID | No | The account to use when no AWS account is mapped to the environment |

### Logs capability options

| Option | Label | Default | Meaning |
|---|---|---|---|
| `log_group_names` | Log Group Names | (required) | Comma-separated log group selectors. See [Log group selectors](#log-group-selectors) |
| `base_filter` | Base Filter Expression | (empty) | A Logs Insights expression, with no leading `filter`, that every search must match. Supports the template variables |
| `message_field` | Message Field | `@message` | The field that holds the log message |
| `timestamp_field` | Timestamp Field | `@timestamp` | The field that holds the log time |
| `level_field` | Level Field | `level` | The field that holds the log level |
| `poll_interval_ms` | Poll Interval (ms) | `500` | How often Imbi polls a running Insights query |
| `timeout_seconds` | Query Timeout | `30` | How long Imbi waits for a query |

### Configuration capability options

| Option | Label | Default | Meaning |
|---|---|---|---|
| `path_prefix` | Parameter Path Prefix | (required) | The SSM path of the project parameters, for example `/imbi/${environment}/${project_slug}/`. It must start with `/` and must not be `/` only. Supports the template variables |
| `kms_key_id` | KMS Key ID | `alias/aws/ssm` | The KMS key for `SecureString` writes |
| `timeout_seconds` | Request Timeout | `15` | The timeout of each request, in seconds |

### Credentials

You do not enter credentials. The plugin registers an IAM Identity Center
OIDC client the first time a user connects. It stores the client ID, the
client secret, and the client scopes as the `client_id`, `client_secret`,
and `client_scopes` credentials. It registers a new client when the secret
expires or the scopes change.

## Map environments to AWS accounts

Each Imbi environment can map to one AWS account. Imbi then gets
credentials for that account when a user selects the environment.

1. Open **Admin > *Organization* Admin > Environments**.
2. Open the environment.
3. In the **AWS: MAPS_TO** card, paste the 12-digit AWS account ID.
4. Click **Map AwsAccount**.

Imbi makes an `AwsAccount` record for the account ID if none exists. The
UI sets only the account ID. An `AwsAccount` can also hold a
`default_role_name` and a `default_region`. To set them, use the
plugin-entity API: `/admin/plugins/aws/entities/AwsAccount`.

### How Imbi selects the account, role, and region

For each call, Imbi uses the first value that it finds:

| Value | Order |
|---|---|
| Account | The account mapped to the environment, then the account stored at connect time (`default_account_id`) |
| Role | The `default_role_name` of the mapped account, then the integration `default_role_name`, then `aws_role_name` stored at connect time, then the `default_role_name` option of the identity plugin |
| Region | The `default_region` of the mapped account, then the integration `region`, then `aws_region` stored at connect time, then the `region` option of the identity plugin |

If Imbi finds no account or no role, the call fails with `503` and a
message that names the environment.

The account lookup uses the environment slug only. If two organizations
have an environment with the same slug, the lookup uses the first mapping
that it finds.

## Template variables

`default_role_name`, `log_group_names`, `base_filter`, and `path_prefix`
can use these variables:

| Variable | Value |
|---|---|
| `${project_slug}` | The project slug |
| `${org_slug}` | The organization slug |
| `${team_slug}` | The slug of the owning team |
| `${environment}` | The selected environment slug |
| `${project_id}` | The project ID |
| `${project_type_slug}` | The first project type slug, changed by `project_type_path_map` |

All four options accept all six variables. A template with an unknown
variable fails. In a `regex:` log group
selector, Imbi escapes the variable values.

## Log group selectors

Each entry of `log_group_names` is one of these:

| Form | Example | Meaning |
|---|---|---|
| A literal name | `/ecs/${project_slug}` | One log group |
| A glob | `/ecs/${project_slug}-*` | Groups that match `*`, `?`, or `[...]` |
| `regex:<pattern>` | `regex:^/ecs/.*-api$` | Groups that match the regular expression |
| `prefix:<name>` | `prefix:/ecs/${project_slug}` | CloudWatch source selection by prefix |

Imbi matches globs and regular expressions itself. It lists log groups
with `DescribeLogGroups` and uses the first 50 matches. You cannot mix
`prefix:` entries with other forms. You can have 5 `prefix:` entries at
most.

## Configuration values

The **Configuration** tab shows the parameters under `path_prefix`. The
plugin maps the Imbi data types to SSM types:

| Imbi data type | SSM type |
|---|---|
| String | `String` |
| String List | `StringList` |
| Secret | `SecureString` |

A key must be relative to the prefix. A key that starts with `/` or holds
`..` fails. A write overwrites the parameter if it exists. Imbi records
each change in the operations log.

## Doctor checks

None.

## Webhook actions

None.

## Lifecycle

None.

## Known limits

- AWS cannot be a login provider. The sign-in flow does not handle the
  device-code step, and the AWS profile has no email address. Use AWS
  only for user connections.
- One Insights query returns 10,000 rows at most.
- Each user must connect at **Settings > Connections** before the **Logs**
  and **Configuration** tabs work for that user.
