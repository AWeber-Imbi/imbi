# imbi-plugin-openai

OpenAI workload identity federation (WIF) for Imbi. The plugin adds:

- The OpenAI token exchanger. An OpenAI AI Provider can then use workload
  identity instead of a stored key (Admin, AI Models).
- The `openai_wif` secret provider. A dynamic binding then mints a
  short-lived OpenAI token for the agent of the task. The harness does
  not use it yet: the Claude Agent SDK calls only the Anthropic API.

## How it works

1. The organization selects an identity source (for example `aws_sts`) in
   Admin, Secrets, Identity.
2. In the OpenAI dashboard, create a workload identity provider for the
   issuer of that identity source. Set its audience to
   `https://api.openai.com/v1`. Imbi always requests this audience.
   See the [OpenAI guide](https://developers.openai.com/api/reference/workload-identity-federation).
3. Create a service account and a mapping. The mapping matches the role
   ARN (`sub`) and the request tag `imbi_ai_provider` (an AI Provider) or
   `imbi_agent` (an agent). AWS request tags are nested in the JWT, so
   expose them with a CEL transformation, for example
   `assertion["https://sts.amazonaws.com/"]["request_tags"]["imbi_ai_provider"]`.
4. Give Imbi the ids: on the AI Provider (Admin, AI Models, the key icon)
   or in a dynamic `openai_wif` binding.
5. At use time, Imbi gets a new identity JWT that lasts 55 minutes, and
   exchanges it at `https://auth.openai.com/oauth/token` (RFC 8693). The
   token never outlives the JWT.

## Target

| Field                  | Required | Description                               |
| ---------------------- | -------- | ----------------------------------------- |
| `identity_provider_id` | yes      | The OpenAI workload identity provider id. |
| `service_account_id`   | yes      | The OpenAI service account id.            |

The provider takes no configuration.
