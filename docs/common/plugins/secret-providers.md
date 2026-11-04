# Secret Providers

A secret provider connects the imbi-api secrets broker to an external
secret system. It is not a capability: an organization configures a
provider in **Admin, Secrets**, not in an Integration, and a provider has
no Integration credentials.

A plugin declares its provider classes in
`PluginManifest.secret_providers`:

```python
manifest = PluginManifest(
    slug='aws',
    ...,
    secret_providers=[AwsSecretsManager],
)
```

imbi-api creates one instance of each class when it first needs the
provider type. Two plugins cannot declare the same `type`: the second one
is ignored, and imbi-api logs an error.

| Plugin | Type | Issues |
|---|---|---|
| AWS | `aws_secrets_manager` | Static and rotated secrets from the organization's account |
| GitHub | `github_app` | GitHub App installation tokens, one for each resolution |

## The contract

Subclass `SecretProvider` (`imbi.common.plugins.secrets`) and set three
class attributes:

- `type` — the provider type that the provider rows store
- `label` — the name that the UI shows
- `capabilities` — the `SecretCapability` values that the provider has.
  The broker refuses a binding whose credential class needs a capability
  that the provider does not have

Every provider must override `validate_config` and `validate_locator`:
the base methods raise `NotImplementedError`. Then override `health`,
`validate_binding`, `resolve`, `renew`, and `revoke` for the capabilities
that the provider has. The base methods raise `BrokerError`
(`operation_not_supported`, `provider_lease_not_renewable`, or
`provider_lease_not_revocable`). The base `check_config` and
`check_locator` do nothing: override them only when the provider must
check a configuration or a locator against the external system.

Two optional methods are for providers that issue repository tokens:

- `repository(config, url)` — return `(host, owner/name)` for the
  repository link of a project. The agent runner clones that repository.
  The default returns `None`.
- `check_key_host(host)` — validate the host of a provider key (see
  below). The default raises `ValueError`.

## Rules

- Put secret material only in `Material`. It has no readable `repr`, and
  it cannot be pickled or serialized.
- Translate every error of the external system into a `BrokerError` with
  a safe reason code. Never put a provider response, a header, or a value
  in an error or a log.
- Use `validate_model` to validate a configuration or a locator. Its
  error names the fields only, never the input values.

## The host

The constructor gets a `SecretProviderHost`, which gives the broker
services to the provider:

- `graph()` — the graph of imbi-api
- `provider_key(...)` — read a provider key: a binding that only imbi-api
  reads, for example the private key of a GitHub App. No grant gives a
  provider key to a task.
- `check_provider_key(...)` — check that a binding is a provider key for
  a host and App id, without reading it

## API reference

::: imbi.common.plugins.secrets.SecretProvider

::: imbi.common.plugins.secrets.SecretProviderHost

::: imbi.common.plugins.secrets.Material

::: imbi.common.plugins.secrets.ResolveContext

::: imbi.common.plugins.secrets.BrokerError
