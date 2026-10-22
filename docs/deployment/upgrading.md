# Upgrading

This page tells you what to do when you upgrade Imbi. The first part is the
procedure for every upgrade. The second part has one section for each
release that needs manual steps, newest release first.

Use 2.39.1 or later for a new install.

## Upgrade procedure

1. Read the release sections below, from the release after your current
   version up to the target release. If you skip releases, you must do the
   steps of each release that you skip.
2. Set the image tag to the target release. Do not use `latest` in
   production.
3. Do the steps that the release sections tell you to do before you deploy.
4. Deploy the new image.
5. Run the setup commands that the release sections name, in this order:

    ```bash
    imbi-api setup-permissions
    imbi-api setup-service-accounts
    imbi-api setup-clickhouse
    imbi-api setup-prompts
    ```

    All four commands are idempotent. If you skip releases, run each command
    one time. One run applies the changes of all the releases.
    `setup-permissions` must run before `setup-service-accounts`, because
    `setup-service-accounts` gives each internal service account a role by
    name. When more than one organization exists, run
    `imbi-api setup-service-accounts --organization <slug>`.
    [Applying Upgrades](../getting-started/setup.md#applying-upgrades)
    tells what each command does.

6. If a release adds an Iggy stream, restart the Iggy connectors runtime
   (iggy-connect) after `setup-clickhouse`. The runtime reads its sink
   configuration one time, at startup. The sink writes to the ClickHouse
   table that has the same name as the stream, so the table must exist
   first.
7. Do the other steps of the release sections, for example the maintenance
   operations.

imbi-api applies the PostgreSQL graph schema and the relational schemas
(`agent_runtime`, `workflows`, `workflow_runtime`, `secrets`, `harness`) at
startup. You do not run a command for them.

### Where to run the commands

Run each command in a container of the new release that has the imbi-api
environment.

| Deployment | Command |
|---|---|
| Kubernetes | `kubectl -n <namespace> exec deploy/<deployment> -- imbi-api <command>` |
| Docker Compose | `docker compose exec imbi imbi-api <command>` |
| Docker | `docker exec <container> imbi-api <command>` |

On Kubernetes, the Deployment name is the release name, or
`<release>-imbi` when the release name does not contain `imbi`. Use the
`all` mode release, or the `api` mode release when you run the services
separately.

To restart iggy-connect:

| Deployment | Command |
|---|---|
| Kubernetes | `kubectl -n <namespace> rollout restart deployment/<deployment>-connect` |
| Docker Compose | `docker compose restart iggy-connect` |
| Docker | `docker restart <iggy-connect container>` |

## Releases with no manual steps

These releases need only the new image: 2.39.1, 2.37.0, 2.35.1, 2.34.0,
2.30.0, 2.29.0 to 2.29.4, 2.27.0, 2.26.1, 2.21.0, 2.21.1.

## Next release

1. Run `imbi-api setup-permissions`. It gives the `developer` role
   `project:deployment:read`, `project:deployment:write`,
   `project:commits:read`, `project:commits:write`,
   `project:pull-requests:read`, `project:pull-requests:write`, and
   `operations_log:read`. It gives the `default` and `readonly` roles
   `project:deployment:read`, `project:commits:read`, and
   `project:pull-requests:read`.
2. Make sure that each platform administrator who manages deployments is a
   member of each organization of those projects. The deployment,
   commit-sync, and pull-request-sync routes now use only the role in the
   organization of the path. A platform administrator who is not a member
   gets `403 organization_forbidden`. See
   [Roles and Permissions](../admin/roles-and-permissions.md#permissions-across-organizations).
3. Examine the `IMBI_AUTH_PASSWORD_*` and `IMBI_AUTH_RATE_LIMIT_*` values
   in your environment. Imbi now reads them. Before, it used the defaults.
   Remove `IMBI_AUTH_RATE_LIMIT_API_KEY`. Imbi does not have this setting
   now. The password rules now also apply when an administrator creates a
   user with a password.
4. Examine the `allowed_domains` option of your login provider. Imbi now
   rejects a sign-in from a domain that is not in a list that is not empty.
   See [Authentication](../admin/authentication.md#sso-login-providers).
5. Check each client credential that has scopes, and each client that
   sends `scope` to `POST /auth/token`. A client-credentials token now
   gets only the permissions in its scopes, as an API key does. Before,
   it got all the permissions of the roles of the service account. The
   seeded `imbi-scheduler` and `imbi-workflows` credentials have no
   scopes, so they do not change.
6. **Helm chart: the chart now runs in production mode.** The new
   `environment` value defaults to `production`, and the chart sets
   `ENVIRONMENT` and `IMBI_API_ENVIRONMENT` to it. In production mode Imbi
   does not generate `IMBI_AUTH_JWT_SECRET`, `IMBI_AUTH_ENCRYPTION_KEY`, or
   `IMBI_CONFIG_ENCRYPTION_KEY` and fails without them, and the auth cookies
   get the `Secure` flag. Before you upgrade:
    - Set `auth.configEncryptionKey` to a new Fernet key, or add a
      `config-encryption-key` key to your `existingSecret`. The chart
      refuses to render without it. Before this release, each process of a
      chart install generated its own key, so Imbi cannot decrypt the
      configuration secrets saved before the upgrade (AI provider keys, MCP
      server credentials). Enter them again after the upgrade.
    - Set `service.publicApiUrl` in `all` and `ui` mode. The chart sets
      `VITE_API_URL` to it and refuses to render without it.
    - `iggyConnect.enabled` now defaults to `true`. Set `iggyConnect.apiKey`,
      `iggyConnect.iggy.address`, and `iggyConnect.iggy.password`, or set
      `iggyConnect.enabled: false` if you run the connectors runtime
      yourself.
    - In `gateway` mode, set `gateway.serviceAccount.token` (or the
      `gateway-sa-token` key of `existingSecret`).
    - In `slackbot` mode, set `slackbot.botToken`, `slackbot.appToken`, and
      `assistant.anthropicApiKey`, or the matching `existingSecret` keys.

    New chart values: `environment`, `auth.configEncryptionKey`,
    `externalValkey.url`, `extraEnv`, `extraEnvFrom`, `slackbot.*`,
    `iggyConnect.extraEnv`, and `iggyConnect.extraEnvFrom`. See
    [Kubernetes Deployment](kubernetes.md).
7. **Container entrypoint.** `gateway` mode now also requires
   `CLICKHOUSE_URL`, `IGGY_URL`, `IMBI_AUTH_ENCRYPTION_KEY`, and
   `IMBI_GATEWAY_API_TOKEN`. `slackbot` mode now also requires
   `IMBI_AUTH_JWT_SECRET`. The image no longer exposes port 2019.
8. **`setup-clickhouse` exits with status 1** when a DDL statement fails. It
   still runs the other statements first. An upgrade script must check
   this status, for example with `set -e`, and stop the upgrade when it
   is not 0.
9. Optional: the **Semantic versioning** format now accepts a leading `v`
   (`v1.2.3`). An organization or a project type that turned it on before
   this release keeps the old pattern. To store the new pattern, click
   **Save changes** on **Default Settings**. For a project type, turn
   **Semantic versioning** off and on again, then save it. See
   [Catalog settings](../admin/catalog-settings.md).
10. If you use a `config.toml` file, examine it against your environment
    variables and `.env` entries. An environment variable or `.env` entry
    now wins over the same key in `config.toml`. Before, a `[server]` or
    `[storage]` key in the file won.
    Before you upgrade, correct or remove each `[server]` and `[storage]`
    value that is not valid for its setting. Before, Imbi ignored the file
    when such a value failed validation. Now the service does not start,
    or storage fails. An environment variable or `.env` entry for the same
    key replaces the file value, so the file value is then not checked.
    Also, every service now reads the `[auth]`, `[clickhouse]`,
    `[embeddings]`, `[plugins]`, `[postgres]`, `[releases]`, `[ssl]`, and
    `[valkey]` sections, and imbi-api reads `[email]`. Before, the services
    ignored them. Remove the keys that you do not want to apply. See
    [`config.toml`](../api/configuration.md#configtoml).

## 2.39.1

No manual steps. These changes can affect you:

- Imbi now refuses password logins when local authentication is off on the
  **Auth Providers** page. Before 2.39.1, users with a password could still
  log in. If single sign-on fails while local authentication is off, call
  `PUT /admin/local-auth` with `{"enabled": true}` with an admin API key or
  a service account token. See [Authentication](../admin/authentication.md).
- The Google auth provider now rejects a sign-in when the `hd` claim does
  not match `hosted_domain`. Personal Google accounts have no `hd` claim, so
  Imbi rejects them when `hosted_domain` is set.

Do not install 2.39.0 on a new system. Its image cannot create the Iggy
topics, and imbi-api exits at startup. 2.39.1 corrects this.

## 2.39.0

No setup commands. These changes can affect you:

- A request to an organization route gets the permissions of the role in
  the organization of the path only. Before 2.39.0, it got the union of the
  roles in all the organizations of the user. Examine the roles of users
  that are members of more than one organization. See
  [Roles and Permissions](../admin/roles-and-permissions.md#permissions-across-organizations).
- The GitHub Doctor check `homepage-url-match` needs `IMBI_UI_URL` on
  imbi-api. Without it, the check gives one warning and no repair.
  Repository homepages that the lifecycle sync wrote before 2.39.0 are dead
  links. The check reports them as **fail**, and its **Fix** rewrites them.

## 2.38.1

Set `IMBI_INTERNAL_WORKFLOWS_URL` on imbi-api to the in-cluster URL of
imbi-workflows, for example `http://imbi-workflows:8006`. Without it, the
**System health** card on the admin overview shows Workflows as "not
configured".

## 2.38.0

Before you deploy:

- Change each `IMBI_ASSISTANT_SYSTEM_PROMPT` and
  `IMBI_SLACKBOT_SYSTEM_PROMPT` override to Jinja syntax, for example
  `{{ display_name }}` instead of `{display_name}`. Imbi ignores an override
  that it cannot parse.
- Update the API clients of the AI model catalog. The routes moved from
  `/organizations/{org}/ai-providers` and `/organizations/{org}/ai-models`
  to `/ai-providers` and `/ai-models`.

After you deploy:

1. Run `setup-permissions`, `setup-service-accounts`, `setup-clickhouse`,
   and `setup-prompts`.
    - `setup-permissions` adds the `prompt:*`, `agent:*`, `agent_task:*`,
      `workflow:*`, `secret_*`, `harness_pool:read`, and
      `agent_platform_config:write` permissions. It also changes the grants
      of the `imbi-scheduler` and `imbi-gateway` roles and adds the
      `imbi-workflows` role.
    - `setup-service-accounts` adds the `imbi-workflows` service account. In
      `all` mode the container does this step at startup.
    - `setup-clickhouse` adds the `agent_task_events`, `agent_usage`,
      `workflow_runs`, `workflow_run_events`, and `secret_audit_events`
      tables.
    - `setup-prompts` adds the default prompts of imbi-assistant and
      imbi-slackbot. Until you run it, both use their packaged prompts.
2. Restart iggy-connect. The release adds five streams, with the same names
   as the new tables.
3. Edit and save each webhook one time. A webhook made before 2.38.0 has no
   owner, and its `create_agent_task` rules cannot start a task.
4. If an install has a CMS copy of `imbi-slackbot/system`, publish the new
   "Agent Tasks" section of the packaged prompt in that copy.

The release notes also tell you to run `imbi-api setup` again, to give the
organization that setup made an id. You do not have to do this. imbi-api
gives an id to each organization and user that has none, at startup.

Steps for the new features, when you use them:

- **Workflows.** imbi-workflows runs in `all` mode. To run it as its own
  release, see [Kubernetes: Workflows](kubernetes.md#workflows) and set
  `workflows.schedulerUrl`. For schedule and webhook triggers, add the
  `imbi-scheduler` and `imbi-gateway` service accounts to each organization
  that uses them. The `imbi-workflows` role does not include
  `integration:act-as-service`. Give it to the service account if workflows
  deploy projects. See [Workflows](../admin/workflows.md).
- **Agent runners.** Install the `helm/imbi-harness` chart for each runner
  pool. See [Agent Runners](agent-runners.md).
- **Secrets.** The AWS secrets provider uses the AWS identity of imbi-api.
  The Helm chart does not give imbi-api an AWS identity. Add one, for
  example with IRSA or EKS Pod Identity. See [Secrets](../admin/secrets.md).
- **Metrics.** The Helm chart adds Prometheus scrape annotations. If you do
  not use the chart, add the annotations yourself. See
  [Operations: Metrics](operations.md#metrics).

## 2.36.0

Run `setup-clickhouse`. It adds the `email_audit` table. Before 2.36.0,
Imbi stored no password-reset email audits.

## 2.35.0

Restart iggy-connect. The release moves every ClickHouse write to Iggy and
adds 14 streams. Without the restart, Imbi publishes to the new streams and
nothing writes them to ClickHouse.

## 2.33.0

After you deploy, run these maintenance operations from
**Admin > Global Admin > Maintenance**, in this order:

1. **Report Re-stamped Commit Push Times (dry run)**
   (`commit-pushed-at-check`)
2. **Repair Re-stamped Commit Push Times** (`commit-pushed-at-repair`)

They restore the commit push times that the commit sync overwrote.

## 2.32.3

`IMBI_API_URL` must include the scheme, for example
`https://imbi.example.com/api`. A value without a scheme stops the service
at startup.

## 2.32.2

On Docker and Docker Compose, rename `ACTIONS_IMBI_TOKEN` to
`IMBI_GATEWAY_API_TOKEN`. The Helm chart sets the new name from the
existing `gateway-sa-token` secret key, so Helm installs need no change.

## 2.32.1

imbi-gateway reads the URL of imbi-api from `IMBI_INTERNAL_API_URL`. Set it
when the gateway runs as its own service. 2.32.2 removes the
`ACTIONS_IMBI_URL` fallback.

## 2.32.0

This release adds Apache Iggy. Before you deploy:

1. Deploy an Apache Iggy server. See [Operations: Apache Iggy](operations.md#apache-iggy).
2. Set `IGGY_URL` on every service. The Helm value is `externalIggy.url`.
3. Run the Iggy connectors runtime and set `IMBI_IGGY_CONNECTORS_API_KEYS`
   on imbi-api. On Kubernetes, set `iggyConnect.enabled`. Without the
   runtime, gateway events do not get to ClickHouse. See
   [Kubernetes: The connectors runtime](kubernetes.md#the-connectors-runtime)
   or [Docker: The Iggy connectors runtime](docker.md#the-iggy-connectors-runtime).

After you deploy, run `setup-permissions`. It adds the five `ai_model:*`
permissions.

## 2.31.0

The gateway uses `publish_release` as a service account with no user. From
2.31.0, a service account must have `integration:act-as-service` to use the
credential of an integration. Without it, `publish_release` gets
`403 service_credential_forbidden`.

1. Run `setup-permissions`. It adds `integration:act-as-service`.
2. Give the permission to the `imbi-gateway` service account. You cannot
   change a built-in role, so create a custom role that has the permissions
   of `imbi-gateway` and `integration:act-as-service`. See
   [Roles and Permissions](../admin/roles-and-permissions.md#create-a-custom-role).
3. Give the service account that role in each organization that owns the
   projects it deploys.

A service account API key with an explicit `scopes` list keeps its scopes.
Issue a new key if the scopes do not include the permission. Imbi caches
API key authentication for 60 seconds, so a grant can take one minute to
apply.

To let autonomous deployments into an environment, turn on
`allow_autonomous` on that environment. It is off by default.

## 2.28.0

After you deploy, run **Repair Deployments Mislabelled Rolled Back**
(`deployment-status-repair`) from **Admin > Global Admin > Maintenance**.
It restores the `success` status that an earlier release overwrote on
deployment nodes.

## 2.26.2

Run `setup-clickhouse`. It adds the `commit_drift` table.

## 2.26.0

Run `setup-permissions` and `setup-clickhouse`.

- `setup-permissions` adds `component:read` and `component:write`.
- `setup-clickhouse` adds the `release_component_batches`,
  `release_components`, and `maintenance_log` tables.

## 2.25.0

No setup commands.

- A direct API call that promotes or cuts a release from a commit with a
  `fail` CI status now gets `409`. Send `acknowledge_ci_failure` on the
  request to continue.
- Examine the rule order of each webhook that you edited in the admin UI
  before 2.25.0. `create_release` must come before
  `add_deployment_event`, and `publish_release` must come after both.
- On the `add_deployment_event` rule, set
  `"external_run_url_selector": "/payload/deployment_status/log_url"` and
  `"external_run_id_selector": "/payload/deployment/id"`.
- The `mainline_branches` option of an integration replaces the default
  branches (`main`, `master`). List every mainline branch.

## 2.24.0

No setup commands. If you set the `artifact_workflow` capability option on
a project, connect the `deployment_status` webhook to the
`publish_release` and `block_release` actions. Without them, a promoted tag
does not become a release.

## 2.23.0

- Run `setup-clickhouse`. In 2.22.0, the `scheduler_runs` table failed to
  create on some ClickHouse versions. 2.23.0 corrects the DDL.
- Set `IMBI_INTERNAL_SCHEDULER_URL` on imbi-api to the in-cluster URL of
  imbi-scheduler, for example `http://imbi-scheduler:8005`. Without it, the
  **System health** card shows the scheduler as not configured.

## 2.22.0

This release adds imbi-scheduler.

1. Run `setup-permissions`. It adds the `scheduled_task:*`,
   `scheduler:impersonate`, and document analytics permissions. It also
   writes all the grants of the built-in roles. Before 2.22.0, the built-in
   roles got only one grant.
2. Run `setup-service-accounts`. It adds the `imbi-scheduler` and
   `imbi-gateway` service accounts. In `all` mode the container does this
   step at startup.
3. Run `setup-clickhouse`. It adds the `scheduler_runs`,
   `document_read_events`, and `document_read_sessions` tables.
4. Run **Reindex Search** (`search-reindex`) one time from
   **Admin > Global Admin > Maintenance**.

## 2.20.0

After you deploy, run **Backfill Deployments to Operations Log**
(`opslog-backfill`) one time from **Admin > Global Admin > Maintenance**.
For the best result, run **Sync Deployments** and **Sync Commits & Tags**
first.
