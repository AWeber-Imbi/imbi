# imbi-plugin-anthropic

Anthropic workload identity federation (WIF) for Imbi. The plugin adds the
`anthropic_wif` secret provider. An agent's model key binding then holds
no API key. Each resolution mints a short-lived `sk-ant-oat01` token for
that agent.

## How it works

1. The organization selects an identity source (for example `aws_sts`) in
   Admin, Secrets, Identity.
2. For each agent, an admin creates an Anthropic service account and a
   federation rule. The rule matches the role ARN (`sub`) and the
   agent's `imbi_agent` request tag.
3. A dynamic `anthropic_wif` binding holds the Anthropic ids of that
   agent. The agent's **Model key** names the binding.
4. At resolution time, Imbi gets a new identity JWT, exchanges it at
   `https://api.anthropic.com/v1/oauth/token`, and gives the token to
   the runner.

## Binding locator

| Field                | Required | Description                                          |
| -------------------- | -------- | ---------------------------------------------------- |
| `organization_id`    | yes      | Anthropic organization id.                           |
| `federation_rule_id` | yes      | The federation rule of the agent.                    |
| `service_account_id` | yes      | The service account of the agent.                    |
| `workspace_id`       | no       | Required when the rule names more than one workspace. |

The provider takes no configuration.
