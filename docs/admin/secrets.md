# Secrets

The **Secrets** section controls which secrets agents can use. Imbi does not
store secret values. The values stay in AWS Secrets Manager. Imbi reads a
value only when an agent or its runner needs it, and only when a grant
allows the request.

Open the section at **Admin > <organization> Admin > Secrets**. Each organization has
its own providers, bindings, and grants.

Setup has four steps:

1. [Prepare AWS](#prepare-aws): a role that Imbi can assume, and the secrets.
2. [Add a provider](#add-a-provider): the AWS account and role.
3. [Add a binding](#add-a-binding): a name in Imbi for one AWS secret.
4. [Add a grant](#add-a-grant): which agents can use which bindings, and for
   what.

## How the parts connect

| Part | What it is | Example |
|---|---|---|
| Secret | The value, in AWS Secrets Manager | `imbi/grafana` = `{"token": "glsa_..."}` |
| Provider | The AWS account and role that Imbi uses to read secrets | `aws-prod`, role `arn:aws:iam::123456789012:role/imbi-secrets` |
| Binding | A **reference** that you choose, mapped to one AWS secret | `secret://grafana/api` → `{"secret_id": "imbi/grafana"}` |
| Grant | Which agents can use which bindings, for which purposes | Agent `ops-helper` may use `secret://grafana/api` for `grafana` |

The reference is a name that you make up. It is not an AWS name. Agents,
MCP servers, and the model settings use the reference, so you can move a
secret to a different AWS secret without changing them.

## Prepare AWS

Imbi never uses AWS access keys for secrets. imbi-api assumes a role in your
account for each request.

### imbi-api identity

The imbi-api pods need an AWS identity that can call `sts:AssumeRole` on your
role, for example IRSA or EKS Pod Identity. The Imbi Helm chart does not set
this up. Your platform team must add it.

### The role

Create an IAM role with this trust policy. Replace the principal with the
imbi-api identity and the organization id with your own:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::111111111111:role/imbi-api"},
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {"sts:ExternalId": "imbi:<organization id>"}
      }
    }
  ]
}
```

The `sts:ExternalId` condition is required. Without it, Imbi refuses the
provider, because another organization could use the role. If you do not
know your organization id, save the provider first: the error message shows
the exact value to put in the trust policy.

Give the role this permission policy. Limit the resources to the secrets
that Imbi may read:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:imbi/*"
    }
  ]
}
```

If a secret uses a customer-managed KMS key, the role also needs `kms:Decrypt`
on that key.

### The secrets

Create each secret in AWS Secrets Manager. The name is your choice. A common
pattern is a prefix, such as `imbi/`, so one policy covers all of them.

A secret can hold one plain text value, or a JSON object. With a JSON
object, a reference can select one member with `#field`, for example
`secret://grafana/api#token`. A field works only on a text secret, not on a
binary secret.

## Add a provider

1. Open the **Providers** tab and click **New provider**.
2. Enter a name: lower case letters, digits, `-`, and `_`.
3. Select **AWS Secrets Manager**.
4. Enter the configuration:

    ```json
    {"region": "us-east-1", "role_arn": "arn:aws:iam::123456789012:role/imbi-secrets"}
    ```

    `account_id` is optional. Access keys and an endpoint URL are refused.

5. Click **Save**.

When you save, Imbi does two checks. It assumes the role with a random
ExternalId, which must fail. Then it assumes the role with your
organization's ExternalId, which must work. If either check fails, the
error shows the ExternalId that the trust policy must require.

Click **Test** on the provider row to check it again later.

## Add a binding

A binding gives one AWS secret a reference in Imbi.

1. Open the **Bindings** tab and click **New binding**.
2. Enter the **Reference**, for example `secret://grafana/api`.
    - Use `secret://<scope>/<path>`.
    - Use only lower case letters, digits, and `_` in each part.
    - Do not add `#field` here. The request adds the field.
3. Select the provider.
4. Keep the **Credential class** at `static` for a secret that you change by
   hand. Use `rotated` for a secret that AWS rotates.
5. Enter the **Locator**, which names the AWS secret:

    ```json
    {"secret_id": "imbi/grafana"}
    ```

    `secret_id` is the secret name or ARN. To pin a version, add
    `version_stage` (for example `AWSCURRENT`) or `version_id`, not both.
    With neither, Imbi reads `AWSCURRENT`.

6. In **Allowed fields**, list the JSON members that requests may select,
   for example `token`. Leave it empty to allow only the whole value.
7. Select the **Allowed delivery modes**. Select `environment` for a secret
   that agents use in commands, and `file_descriptor` for a secret that the
   runner uses (see [Purposes](#purposes)).
8. Optional: in **Allowed delivery targets**, list the environment variable
   names that may receive the value, for example `GRAFANA_TOKEN`.
9. Click **Save**.

Click **Validate** on the binding row to check that the role can see the
AWS secret.

## Add a grant

A grant lets agents use bindings. Exactly one enabled grant must allow a
request, or Imbi denies it.

There are two ways to add one:

- **For one agent:** open the agent, then the **Access** tab, then click
  **Add access**. Select the secret and enter a purpose. This makes an
  `environment` grant for that agent. The same tab has buttons for the
  GitHub purposes.
- **For many agents, or for runner purposes:** open the **Grants** tab and
  click **New grant**.

The grant form has these fields:

| Field | What to enter |
|---|---|
| Agents | The agents that may use the bindings |
| Bindings | The bindings this grant covers |
| Projects | Project ids. Leave empty for any project |
| Purposes | The purposes this grant allows. See [Purposes](#purposes) |
| Delivery modes | How the value may be delivered. Each mode must also be allowed on the binding |
| Maximum TTL (seconds) | How long one read stays valid. Default 900, maximum 3600 |

## Purposes

A purpose says what a secret is for. The broker checks it against the
grant.

The runner uses these purposes itself. The agent never sees the value.
Grant them with the `file_descriptor` delivery mode only.

| Purpose | Used for |
|---|---|
| `model_inference` | The model API key, from the agent's model settings |
| `mcp_server` | Credentials of an MCP server, from its `credential_ref` |
| `workspace_checkout` | Cloning the project repositories |
| `marketplace_fetch` | Fetching plugins from private marketplaces |

The GitHub write purpose uses the `environment` delivery mode:

| Purpose | Used for |
|---|---|
| `github_write` | Pushing, and opening pull requests and issues |

A grant allows each of its purposes with each of its delivery modes. Put
purposes that need different delivery modes in separate grants.

Any other purpose is for the agent's own commands. Choose a short name such
as `grafana` or `npm`: lower case letters, digits, and `_`.

## How an agent uses a secret

When a task starts, Imbi tells the agent which references it may use. The
list comes from the enabled grants for the agent and the task's project that
allow `environment` delivery.

The agent calls the `run_with_secret` tool with a command, and for each
secret a reference, a purpose, and an environment variable name:

```json
{
  "command": "curl -fsS -H \"Authorization: Bearer $GRAFANA_TOKEN\" https://grafana.example.com/api/health",
  "secrets": [
    {"reference": "secret://grafana/api#token", "purpose": "grafana", "env": "GRAFANA_TOKEN"}
  ]
}
```

The value is in the environment of that one command only. Imbi removes the
value from the command output before the agent sees it.

## Check what happened

- **Resolutions** lists the secret reads that are active now.
- **Audit** lists every request, allowed or denied, with the reason.

A denied request names the reason, for example `no_grant`. Check
that the grant includes the agent, the binding, the purpose, and the
delivery mode, and that the project is in the grant's project list or the
list is empty.

See [ADR 0022](../api/adr/0022-agent-harness-and-secrets-broker.md) for the
design.
