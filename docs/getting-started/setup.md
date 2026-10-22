# Initial Setup

After you install Imbi, run the setup command one time. It creates your
organization and your first admin user, and seeds the data that Imbi needs.

Setup needs the PostgreSQL schema. From 2.39.1, setup creates the schema
itself. In 2.39.0, setup cannot connect to a new database and stops with a
`PoolTimeout` error. Run `imbi-api setup-postgres` first to prevent this (see
[issue #469](https://github.com/AWeber-Imbi/imbi/issues/469)).

## Running Setup

### Docker

Setup needs the same PostgreSQL, ClickHouse, and Iggy connections as
imbi-api. Attach the container to the Docker network of those services.
Replace `<network>` with its name. The credentials below are the evaluation
values from the [Installation](installation.md) Compose file. Replace them
with the credentials of your services:

```bash
docker run -it --network <network> \
  -e POSTGRES_URL=postgresql://postgres:secret@postgres/imbi \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IGGY_URL=iggy+tcp://iggy:iggy@iggy:8090 \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-fernet-key \
  ghcr.io/aweber-imbi/imbi:latest setup
```

The entrypoint refuses to run `setup` without `CLICKHOUSE_URL`, `IGGY_URL`,
`IMBI_AUTH_JWT_SECRET`, and `IMBI_AUTH_ENCRYPTION_KEY`. It does not check
`POSTGRES_URL`. Without it, setup connects to PostgreSQL on `localhost`.

### Docker Compose

If you use the Compose file from [Installation](installation.md):

```bash
docker compose run --rm imbi setup
```

### Kubernetes

Run setup in a pod that has the imbi-api environment. That is the `all` mode
release, or the `api` mode release when you run the services separately. The
Deployment name is the release name, or `<release>-imbi` when the release
name does not contain `imbi`:

```bash
kubectl exec -it deploy/<deployment> -- imbi-api setup
```

## What Setup Does

Setup asks for input at steps 1 and 2:

1. **Creates the organization and seeds permissions and roles.** It asks for
   the organization name and slug. The defaults are `AWeber` and `aweber`.
   Type your own values. It then creates the default set of permissions and
   the default roles.
2. **Creates the admin user.** It asks for the email, display name, and
   password. The user is a system admin and has the `admin` role in the
   organization.
3. **Creates the internal service accounts.** These are `imbi-scheduler`,
   `imbi-gateway`, and `imbi-workflows`, each with a least-privilege role
   and a credential. See [Internal Service Credentials](#internal-service-credentials).
4. **Seeds the default prompts.** It creates `imbi-assistant/system` and
   `imbi-slackbot/system` in the prompt CMS (see
   [Prompts](../admin/prompts.md)).
5. **Creates the ClickHouse schema.** It runs the DDL for the analytics
   tables and materialized views.

When the system already has its permissions, roles, an organization, and an
admin user, setup asks
"Continue anyway? This will create additional data." The default answer is
no. To apply the changes of a new release, use the commands in
[Applying Upgrades](#applying-upgrades) instead.

### Internal Service Credentials

imbi-scheduler, imbi-gateway, and imbi-workflows call imbi-api as themselves,
so each needs a credential of its own — the scheduler a client credential (it
has no other way to run a task; see ADR 0002), the gateway an API key it sends
as a bearer token, and imbi-workflows a client credential for the deploy and
rollback steps of a workflow (ADR 0021). Setup handles all three:

- **You supply them.** Set `IMBI_SCHEDULER_SA_CLIENT_ID`,
  `IMBI_SCHEDULER_SA_CLIENT_SECRET`, `IMBI_WORKFLOWS_SA_CLIENT_ID`,
  `IMBI_WORKFLOWS_SA_CLIENT_SECRET`, and `IMBI_GATEWAY_API_TOKEN` (an
  `ik_<id>_<secret>` API key) before running setup, and the accounts are
  seeded to match. This is the path for Helm and Compose, where the values
  already live in a values file or `.env`.
- **Setup supplies them.** Leave them unset and setup generates a credential
  per service and prints it once, as assignments to paste into your
  environment. They cannot be read back afterward.

  That output contains live secrets. Treat it as you would a password: do not
  pipe it anywhere that ships logs off the host.

The scheduler's two variables go together — set both or neither. The same
rule applies to the two `IMBI_WORKFLOWS_SA_*` variables. Half a pair
fails rather than being ignored, because seeding a generated credential instead
would leave the scheduler holding a value that authenticates nobody.

Re-running setup never rotates a working credential, and never narrows a role
you have since widened. In `all` mode the container entrypoint provisions all three
credentials itself when the environment does not supply them — for the
scheduler and imbi-workflows, only when both of a service's variables are
absent.

## Applying Upgrades

`setup` is interactive and covers everything, which is more than an
existing instance needs when a release only adds ClickHouse tables or new
permissions. These commands run those steps on their own, without prompting
or touching the admin user:

```bash
imbi-api setup-clickhouse        # apply the ClickHouse schema only
imbi-api setup-postgres          # apply the PostgreSQL graph schema only
imbi-api setup-permissions       # seed permissions and default roles only
imbi-api setup-service-accounts  # seed the internal service accounts only
imbi-api setup-prompts           # seed the default prompts only
```

All of them are idempotent and safe to re-run. `setup-permissions` also
refreshes each default role's permission grants and prunes permissions retired
by a previous release; run it before `setup-service-accounts`, which grants each
account a role by name. `setup-service-accounts` takes `--organization <slug>`
when more than one organization exists. `setup-prompts` creates each default
prompt as version 1 with a `stable` label only when the prompt does not exist.
It never changes an existing prompt.

`setup-postgres` does the same work that imbi-api does at startup, so you
seldom need it. imbi-api also applies its relational schemas (`agent_runtime`,
`workflows`, `workflow_runtime`, `secrets`, and `harness`) at startup. No
command applies them.

### Upgrading

After you upgrade, do these steps when the release notes tell you to:

1. Run `imbi-api setup-permissions` when the release adds permissions or
   changes the grants of a default role.
2. Run `imbi-api setup-service-accounts` when the release adds an internal
   service account. For example, 2.38 adds `imbi-workflows`. In `all` mode the
   container entrypoint does this step at boot.
3. Run `imbi-api setup-clickhouse` when the release adds ClickHouse tables or
   materialized views.
4. Run `imbi-api setup-prompts` when the release adds a default prompt. Until
   you run it, imbi-assistant and imbi-slackbot use their packaged prompts.
5. Restart iggy-connect when the release adds an Iggy stream. iggy-connect
   gets its sink configuration from imbi-api one time, at startup. imbi-api
   makes one sink for each stream in `imbi.common.iggy.TOPICS`, so a new stream
   gets no sink until iggy-connect restarts. Run `setup-clickhouse` first,
   because the sink writes to the ClickHouse table of the same name.

An upgrade from 2.37 to 2.38 needs all five steps. The new ClickHouse tables
and Iggy streams are `agent_task_events`, `agent_usage`, `workflow_runs`,
`workflow_run_events`, and `secret_audit_events`.

## Post-Setup

After setup completes, open Imbi at `http://localhost:8080` (or your
configured host) and log in with the admin user you created.

In `all` mode, imbi-scheduler and imbi-workflows start only when the
container seeds the internal service accounts at startup. If the container
started before you ran setup, restart it, so that the seeding runs again.

Next:

- [Authentication](../admin/authentication.md): set up single sign-on
- [Users, Teams, and Organizations](../admin/users-teams-organizations.md): add users
- [Blueprints](../admin/blueprints.md): define custom metadata schemas
- [AI Models](../admin/ai-models.md) and [Secrets](../admin/secrets.md):
  configure the AI providers and the secrets that agents use
- [Agent Runners](../deployment/agent-runners.md): install a runner pool
