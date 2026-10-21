# Initial Setup

After installing Imbi and configuring the environment, you need to run
the setup command to initialize the authentication system and create
your first admin user.

## Running Setup

### Docker

```bash
docker run -it \
  -e CLICKHOUSE_URL=clickhouse+http://default:password@clickhouse:8123/imbi \
  -e IMBI_AUTH_JWT_SECRET=your-secret \
  -e IMBI_AUTH_ENCRYPTION_KEY=your-key \
  ghcr.io/aweber-imbi/imbi:latest setup
```

### Docker Compose

If you are using Docker Compose:

```bash
docker compose run --rm imbi setup
```

### Kubernetes

```bash
kubectl exec -it deploy/imbi -- imbi-api setup
```

## What Setup Does

The setup command performs the following:

1. **Seeds the permission system** - Creates the default set of permissions
   used for authorization
2. **Creates default roles** - Sets up `admin`, `developer`, and `readonly`
   roles with appropriate permissions
3. **Creates the admin user** - Interactively prompts for email, display
   name, and password
4. **Creates the internal service accounts** - `imbi-scheduler`,
   `imbi-gateway`, and `imbi-workflows`, each with a least-privilege role
   and a credential
5. **Seeds the default prompts** - Creates `imbi-assistant/system` and
   `imbi-slackbot/system` in the prompt CMS (see
   [Prompts](../admin/prompts.md))
6. **Creates the ClickHouse schema** - Executes the DDL for the analytics
   tables and materialized views

The setup command is idempotent: it checks whether the system has already
been seeded before making changes, so it is safe to run multiple times.

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

After setup completes, you can access Imbi at `http://localhost:8080` (or
your configured host) and log in with the admin credentials you created.

From the admin interface you can:

- Configure OAuth providers for SSO
- Create organizations and teams
- Define blueprints for custom metadata schemas
- Invite additional users
