# Integrations and Plugins

A **plugin** is a Python package that connects Imbi to an external
platform, for example GitHub or PagerDuty. An **integration** is one
configured instance of a plugin in an organization. It holds the
connection options, the encrypted credentials, and the capabilities that
you turn on.

One plugin can have many integrations. For example, one organization can
have a `github` integration for github.com and a second `github`
integration for a GitHub Enterprise Server appliance.

| Term | Scope | Where you manage it |
|---|---|---|
| Plugin | The installation | **Admin > Global Admin > Plugins** |
| Integration | One organization | **Admin > *Organization* Admin > Integrations** |
| Login provider | The installation | **Admin > Global Admin > Auth Providers** |

The **Admin** menu shows only for platform administrators.

For the pages of each plugin, see [Plugins](../plugins/index.md). To write
a plugin, see [Authoring Plugins](../common/plugins/index.md).

## Capabilities

A plugin declares one or more capabilities. Each capability is one kind of
work that Imbi can ask the plugin to do.

| Capability | What it does |
|---|---|
| `identity` | Connects a user to the remote platform with OAuth or a device code. Some identity capabilities can also sign users in to Imbi |
| `configuration` | Shows and edits project configuration values on the project **Configuration** tab |
| `logs` | Searches logs on the project **Logs** tab |
| `deployment` | Reads refs and commits, and creates releases and deployments |
| `lifecycle` | Changes the remote resource when a project is created, changed, archived, relocated, or deleted |
| `webhook-actions` | Gives actions that a webhook rule can call in imbi-gateway |
| `analysis` | Adds findings and fixes to the project **Doctor** |
| `incidents` | Shows incidents on the project **Incidents** tab |
| `commit-sync` | Records commit and tag history |
| `pr-sync` | Records pull request history |

A capability is either *project-scoped* or *organization-wide*. An
organization-wide capability, for example `identity`, applies to the full
integration. A project-scoped capability applies to projects, as
[Assignments](#assignments) describes.

## Plugins

Plugins are installed with the server. You cannot install or remove a
plugin from the UI. The Imbi distribution includes these plugins:
`aws`, `github`, `google`, `logzio`, `oidc`, `pagerduty`, and `sonarqube`.

A plugin that Imbi finds for the first time is **disabled**. Enable it
before you make an integration of it.

1. Open **Admin > Global Admin > Plugins**.
2. Find the plugin in the list. The list shows its capabilities, its
   package version, and the number of integrations in the selected
   organization.
3. Turn on the **Enabled** switch.

The setting is in the database. It stays the same after a restart.

When you disable a plugin, Imbi keeps all integrations of the plugin and
their configuration. Imbi does not resolve the capabilities of these
integrations, and the integration pages show **plugin unavailable**. The
integrations are read-only until you enable the plugin again.

To stop Imbi from loading a plugin at all, add its slug to the
`IMBI_PLUGINS_DISABLED` setting. To load a plugin package that does not
use the `imbi_plugin_*` module name, add its import path to
`IMBI_PLUGINS`.

| Permission | Lets you | Roles that have it |
|---|---|---|
| `admin:plugins:read` | See the installed plugins | `admin` |
| `admin:plugins:manage` | Enable and disable plugins | `admin` |

## Integrations

### Add an integration

1. Select the organization in the top bar.
2. Open **Admin > *Organization* Admin > Integrations**.
3. Click **New integration**.
4. **Plugin**: select the plugin. The list shows only enabled plugins.
5. **Connection**: enter these values:
    - **Name** (required). Imbi makes the slug from the name.
    - **Slug** (required). Lowercase letters, digits, and hyphens. It must
      start with a letter. You cannot change it later.
    - **Options**. The plugin declares these fields. The plugin page lists
      each option.
    - **Credentials**. Required credentials show first. Click
      **Show optional credentials** to see the others.
6. **Capabilities**: turn on each capability that the integration must
   do. Each capability has its default state from the plugin. For a
   project-scoped capability, you can select project types. See
   [Assignments](#assignments).
7. **Review**: examine the values. Click **Create integration**.

### Options and credentials

Options are not secret. Imbi stores them on the integration and shows them
on the integration page. A capability can also have its own options. You
set these under the capability toggle.

Credentials are secret. Imbi encrypts each credential with
`IMBI_AUTH_ENCRYPTION_KEY` before it stores it. Imbi removes spaces at the
start and the end of each value, and does not store an empty value. The UI
never shows a secret credential again after you save it. A credential that
the plugin marks as not secret, for example a GitHub App ID or an OAuth
client ID, shows on the integration page.

### Edit an integration

Open the integration from the list. The integration page has these
sections:

- **Connection**: click an option or a credential to change it. Each
  change saves immediately. A credential row shows only whether a value
  is set.
- **Capabilities**: turn capabilities on or off, change capability
  options, and change the project types. For an `identity` capability that
  uses OAuth, the row shows the **Callback URL** to register with the
  provider. For a `webhook-actions` capability, the row shows the
  **Delivery URL** of each webhook of the integration. To make a webhook,
  see [Webhooks](webhooks.md).
- **Danger zone**: disable or delete the integration.

Click the name to change it.

**Disable** sets the integration status to `inactive`. Imbi keeps the
configuration.

!!! warning
    In this release, the `inactive` status stops only a login provider.
    Imbi continues to use the capabilities of an inactive organization
    integration. The UI has no control to set the status back to
    `active`. To stop an integration, turn off each of its capabilities
    instead.

**Delete** removes the integration, its credentials, its assignments, the
`EXISTS_IN` links of projects to it, and the identity connections of all
users to it. You cannot undo a delete.

### Assignments

A project-scoped capability that is on applies to projects by these rules:

1. **No project types selected.** The capability applies to all projects
   in the organization.
2. **Project types selected.** The capability applies only to projects of
   those types.
3. **Project override.** A project can add its own assignment on its
   settings tab, in the **Integrations** card with **Add Override**. The
   override can change the capability options for that project.

Capability options merge in this order: the integration value, then the
project type assignment, then the project override. The last value wins.

When two or more integrations give the same capability to one project,
mark one assignment as the default. If no assignment is the default, a
request for that capability fails with `400`.

Each assignment can also hold per-environment payloads (`env_payloads`).
The GitHub deployment capability sends them as workflow inputs. The UI does
not edit them. Use the API:
`PUT /organizations/{org_slug}/integrations/{slug}/capabilities/{kind}/assignments`.

| Permission | Lets you | Roles that have it |
|---|---|---|
| `integration:read` | See integrations and assignments | `admin`, `developer`, `default`, `readonly` |
| `integration:create` | Add an integration | `admin` |
| `integration:update` | Change options, credentials, capabilities, and assignments | `admin`, `developer` |
| `integration:delete` | Delete an integration | `admin` |
| `integration:act-as-service` | Use the integration credential with no user identity. See [Act as service](#act-as-service) | `admin` |

## Project links to integrations

A project can *exist in* an integration. Imbi stores this as an
`EXISTS_IN` edge from the project to the integration. The edge holds:

| Field | What it is |
|---|---|
| Identifier | A stable ID of the project in the remote platform, for example a GitHub repository ID, a PagerDuty service ID, or a SonarQube component key |
| API URL | The canonical API URL of the remote resource |
| Dashboard URL | The web page of the remote resource. Imbi stores it in the project links, with the integration slug as the key |

Imbi uses the identifier to route webhooks. imbi-gateway finds the project
of a delivery by its identifier and the integration slug. If no project
has that identifier, imbi-gateway drops the delivery.

There are two ways to make the edge:

- **The plugin writes it.** A lifecycle capability writes the edge when it
  creates a remote resource. A Doctor fix writes it when it repairs the
  link. The plugin also records the identifier as *verified*.
- **You write it.** Open the project settings tab. In the **Integrations**
  card that lists the integrations the project exists in, click **Add**.
  Enter the integration, the identifier, and the URLs. This needs
  `project:write`.

An identifier that you add or edit by hand is not verified. Some features
use only verified identifiers. For example, the `github_app` secret
provider issues GitHub tokens only for a verified repository ID. To verify
an identifier, use the Doctor fix of the plugin. See
[GitHub](../plugins/github.md#doctor-checks).

## Identity connections

An `identity` capability lets each user connect their own account on the
remote platform. Users connect at **Settings > Connections**. Imbi then
calls the remote platform with the token of the user.

For an OAuth identity, register this redirect URL with the provider:

```text
<IMBI_API_URL>/me/identities/<integration id>/callback
```

The integration page shows the full URL in the **Callback URL** field of
the identity capability. The AWS plugin uses a device code and needs no
redirect URL.

## Act as service

A capability call normally uses the identity connection of the user. A
service account has no identity connection. For the `deployment`
capability, a service account can use the credential of the integration
(a token or GitHub App credentials) instead. The service account must
have all of these:

1. The permission of the endpoint, for example
   `project:deployment:write`, in its role in the organization that owns
   the project.
2. `integration:act-as-service`.
3. Membership in the organization that owns the project.

Imbi refuses a service account that does not have
`integration:act-as-service` with `403` and the error
`service_credential_forbidden`. A platform administrator flag does not
bypass this rule. Imbi gives `integration:act-as-service` to no seeded
role except `admin`. Grant it to the role of each service account that
must deploy. For example, the `imbi-workflows` role does not have it.

If the integration has no usable credential, Imbi returns `503` with the
error `no_service_credential`.

In this release, only the `deployment` capability uses this fallback.

## Login providers

A login provider is an integration of a plugin whose `identity` capability
can sign users in: `google`, `github`, `oidc`, and `aws`. A login provider
belongs to no organization, because users sign in before they select one.
You manage login providers at **Admin > Global Admin > Auth Providers**,
not on the **Integrations** page. See
[Authentication](authentication.md#sso-login-providers).

## Related pages

- [Plugins](../plugins/index.md): one page for each plugin
- [Webhooks](webhooks.md): webhooks and rules that call `webhook-actions`
- [Authentication](authentication.md): login providers
- [Roles and permissions](roles-and-permissions.md)
- [Authoring Plugins](../common/plugins/index.md): the plugin contracts
