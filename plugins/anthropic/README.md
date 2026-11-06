# imbi-plugin-anthropic

Anthropic workload identity federation (WIF) for Imbi. The plugin adds the
`anthropic_wif` secret provider. An agent's model key binding then holds
no API key. Each resolution mints a short-lived `sk-ant-oat01` token for
that agent.

## How it works

1. The organization selects an identity source (for example `aws_sts`) in
   Admin, Secrets, Identity.
2. In the Anthropic Console, register the issuer of that identity source.
   The registered issuer must match the `iss` claim of the identity JWT.
   See the [Anthropic setup guide](https://platform.claude.com/docs/en/manage-claude/workload-identity-federation).
3. For each agent, an admin creates an Anthropic service account and a
   federation rule. The rule matches the role ARN (`sub`) and the
   agent's `imbi_agent` request tag. The rule sets the token lifetime
   (`token_lifetime_seconds`). Imbi cannot revoke the token, so keep this
   lifetime short.
4. A dynamic `anthropic_wif` binding holds the Anthropic ids of that
   agent. Select the binding as the agent's **Model key**. This does not
   create a grant: also add a `model_inference` grant for the agent and
   the binding, with delivery mode `file_descriptor`. Without it,
   resolution fails with `no_grant`.
5. At resolution time, Imbi gets a new identity JWT, exchanges it at
   `https://api.anthropic.com/v1/oauth/token`, and gives the token to
   the runner.

The runner does not yet send this token as `Authorization: Bearer`
(WIF plan phase P4). Until then, the runner cannot use an
`anthropic_wif` token for model calls.

## Binding locator

| Field                | Required | Description                                          |
| -------------------- | -------- | ---------------------------------------------------- |
| `organization_id`    | yes      | Anthropic organization id.                           |
| `federation_rule_id` | yes      | The federation rule of the agent.                    |
| `service_account_id` | yes      | The service account of the agent.                    |
| `workspace_id`       | no       | Required when the rule names more than one workspace. |

The provider takes no configuration.
