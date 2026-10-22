# Service Accounts

A service account is a principal for a machine, not for a person. A CI
pipeline, a script, or an Imbi service uses a service account to call the
Imbi API.

Like a user, a service account gets permissions from its role in each
organization that it is a member of. A service account without a
membership has no permissions. A service account is never a platform
administrator.

A service account authenticates with one of two credentials:

| Credential | How it works | Use it for |
|---|---|---|
| API key | A static bearer token. Send it on each request | Simple scripts and services that cannot do an OAuth token request |
| Client credential | A client id and a secret. Exchange them for a short-lived access token with the OAuth 2.0 `client_credentials` grant | Services that can refresh a token |

To manage service accounts, open **Admin > Global Admin > Service
Accounts**. The **Admin** item shows only for platform administrators.

## Permissions

<!-- BEGIN GENERATED: scripts/docs_permissions_subset.py service_account: -->

| Permission | Lets you | Roles that have it |
|---|---|---|
| `service_account:create` | Create service accounts | `admin` |
| `service_account:read` | View service accounts | `admin` |
| `service_account:update` | Update service accounts | `admin` |
| `service_account:delete` | Delete service accounts | `admin` |

<!-- END GENERATED -->

`service_account:update` also covers the memberships, the API keys, and
the client credentials of a service account. The service account routes
are not organization routes. They use the union of your roles in all your
organizations. See
[Permissions across organizations](roles-and-permissions.md#permissions-across-organizations).

## Create a service account

1. Open **Admin > Global Admin > Service Accounts**.
2. Click **New Service Account**.
3. Enter the fields in the table below.
4. Click **Create Service Account**.

| Field | What to enter |
|---|---|
| Display name | Required. Imbi makes the slug from the name |
| Slug | Required. You cannot change the slug later |
| Description | Optional. What the account does and who owns it |
| Account active | On by default. An inactive account cannot authenticate |
| Organization | Required. The first organization of the account |
| Role | Required. The role of the account in that organization |

A new service account has no credentials. Add an API key or a client
credential after you create the account.

## Organization memberships

A service account can be a member of many organizations, with one role in
each.

1. Open the service account.
2. Under **Organization Memberships**, click **Add to Organization**.
3. Select the organization and the role.

To change a role, select a different role in the row of the organization.
To remove a membership, click the remove button in the row.

## API keys

1. Open the service account.
2. Under **API Keys**, click **Create API Key**.
3. Enter a **Key name**, for example `production`.
4. Click **Create**.
5. Copy the key from the **API Key Created** dialog. Imbi shows the key
   one time only. Imbi stores only a hash of the secret.

The key has the form `ik_<key id>_<secret>`. Send it as a bearer token:

```shell
curl --fail -H "Authorization: Bearer ik_..." https://imbi.example.com/api/organizations/
```

The dialog creates a key with no scopes and no expiry. The API
(`POST /service-accounts/{slug}/api-keys`) also accepts these fields:

| Field | Meaning |
|---|---|
| `scopes` | A list of permission names, for example `["project:read"]`. The key gets only the permissions that are both in this list and in the roles of the account. An empty list means all the permissions of the roles. An unknown permission name gives `400` |
| `expires_in_days` | The days until the key expires. The maximum is `IMBI_AUTH_API_KEY_MAX_LIFETIME_DAYS` (default 365). Empty means the key does not expire |

Each row in the key list has two actions:

- **Rotate API key** makes a new secret for the same key id. The old
  secret stops working. Imbi shows the new key one time only.
- **Revoke API key** stops the key. Imbi keeps the revoked key in the list
  for audit.

Each API process keeps a verified key in memory for 60 seconds. A rotated
or revoked key can work for up to 60 seconds after the change.

## Client credentials

1. Open the service account.
2. Under **Client Credentials**, click **Create Credential**.
3. Enter the fields in the table below.
4. Click **Create**.
5. Copy the client id and the client secret. Imbi shows the secret one
   time only.

| Field | What to enter |
|---|---|
| Name | Required. For example `production-api` |
| Description | Optional |
| Scopes | Optional. Permission names, separated by commas, for example `project:read, project:write`. An unknown permission name gives `400` |
| Expires in (days) | Optional. Empty means the credential does not expire. The maximum is `IMBI_AUTH_API_KEY_MAX_LIFETIME_DAYS` |

The client id has the form `cc_<random>`. To get an access token, send a
form-encoded request to `POST /auth/token` under the API prefix:

```shell
curl --fail -X POST https://imbi.example.com/api/auth/token \
  -d grant_type=client_credentials \
  -d client_id=cc_... \
  -d client_secret=...
```

The response has an access token and a refresh token. The lifetimes are
the same as for users. See [Tokens](authentication.md#tokens). Send the
access token as `Authorization: Bearer <token>`. To get a new pair, send
the refresh token with `grant_type=refresh_token`.

You can send `scope` (permission names, separated by spaces) in the token
request. Imbi writes the granted scopes into the token. In this release,
Imbi does not apply those scopes to a client-credential token: the token
gets all the permissions of the roles of the account. To limit a
credential, limit the role of the service account.

**Rotate credential** and **Revoke credential** work like the actions for
API keys.

## Delete or disable a service account

To stop an account without deleting it, open it, turn off **Account
active**, and save. Imbi then refuses its API keys, its client
credentials, and its tokens.

To delete an account:

1. Open the service account.
2. Under **Danger zone**, click **Delete account**.
3. Confirm.

Imbi deletes the account, its API keys, and its client credentials. If
the account is the credential of a runner pool, Imbi refuses the delete
with `409 service_account_in_use`. Change the pool first. See
[Agent Runners](../deployment/agent-runners.md).

## Agent service accounts

Imbi makes a service account for each agent when you create the agent.
The agent acts as this account when it calls the Imbi API. See
[Agents](agents.md).

| Property | Value |
|---|---|
| Slug | `agent-<agent id>` |
| Display name | The name of the agent |
| Membership | The organization of the agent, with no role |

A membership with no role gives no permissions. To let an agent use the
Imbi API tools, give its service account a role in the organization of
the agent (see [Organization memberships](#organization-memberships)).
The **Organization Memberships** card shows a membership with no role as
`readonly`, but that membership gives no permissions.

Keep the agent's service account in one organization only. If it is a
member of more than one organization, Imbi gives the agent no API token
(`service_account_in_other_organizations`). See
[Agent Runners](../deployment/agent-runners.md).

When you delete the agent, Imbi deletes its service account and the
credentials of that account.

## Imbi service accounts

Three Imbi services call imbi-api as their own service account:

| Service account | Role | Credential | Environment variables |
|---|---|---|---|
| `imbi-scheduler` | `imbi-scheduler` | Client credential | `IMBI_SCHEDULER_SA_CLIENT_ID`, `IMBI_SCHEDULER_SA_CLIENT_SECRET` |
| `imbi-gateway` | `imbi-gateway` | API key | `IMBI_GATEWAY_API_TOKEN` |
| `imbi-workflows` | `imbi-workflows` | Client credential | `IMBI_WORKFLOWS_SA_CLIENT_ID`, `IMBI_WORKFLOWS_SA_CLIENT_SECRET` |

imbi-assistant, imbi-mcp, and imbi-slackbot have no service account. They
send the token of the caller to imbi-api.

`imbi-api setup` creates the three accounts in the organization that it
creates. For an install that already exists, or for another organization,
run this command:

```shell
imbi-api setup-service-accounts --organization <organization slug>
```

Run `imbi-api setup-permissions` first, because the command gives each
account the seeded role of the same name. When only one organization
exists, you can omit `--organization`.

For each credential, the command does one of these:

| Case | What the command does |
|---|---|
| The environment variables of the account are set | Writes the credential to match them. For a client credential, set both variables. One variable without the other is an error |
| The variables are not set and the account has a credential | Keeps the credential |
| The variables are not set and the account has no credential | Makes a credential and prints the variable assignments one time. Put them in the environment of the service |

The command does not change the role of an account that already has a
membership in the organization. It does not change **Account active**.

For the extra setup of `imbi-workflows`, see
[Workflows](workflows.md#operator-prerequisites).

## Related pages

- [Roles and Permissions](roles-and-permissions.md)
- [Users, Teams, and Organizations](users-teams-organizations.md)
- [Authentication](authentication.md)
- [Security model](../architecture/security.md)
