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
4. **Creates the internal service accounts** - `imbi-scheduler` and
   `imbi-gateway`, each with a least-privilege role and a credential
5. **Creates the ClickHouse schema** - Executes the DDL for the analytics
   tables and materialized views

The setup command is idempotent: it checks whether the system has already
been seeded before making changes, so it is safe to run multiple times.

### Internal Service Credentials

imbi-scheduler and imbi-gateway call imbi-api as themselves, so each needs a
credential of its own — the scheduler a client credential (it has no other way
to run a task; see ADR 0002), the gateway an API key it sends as a bearer
token. Setup handles both:

- **You supply them.** Set `IMBI_SCHEDULER_SA_CLIENT_ID`,
  `IMBI_SCHEDULER_SA_CLIENT_SECRET`, and `ACTIONS_IMBI_TOKEN` (an
  `ik_<id>_<secret>` API key) before running setup, and the accounts are
  seeded to match. This is the path for Helm and Compose, where the values
  already live in a values file or `.env`.
- **Setup supplies them.** Leave them unset and setup generates a credential
  per service and prints it once, as assignments to paste into your
  environment. They cannot be read back afterward.

  That output contains live secrets. Treat it as you would a password: do not
  pipe it anywhere that ships logs off the host.

The scheduler's two variables go together — set both or neither. Half a pair
fails rather than being ignored, because seeding a generated credential instead
would leave the scheduler holding a value that authenticates nobody.

Re-running setup never rotates a working credential, and never narrows a role
you have since widened. In `all` mode the container entrypoint provisions both
credentials itself when the environment does not supply them — for the
scheduler, only when both of its variables are absent.

## Applying Upgrades

`setup` is interactive and covers everything, which is more than an
existing instance needs when a release only adds ClickHouse tables or new
permissions. Three commands run those steps on their own, without prompting
or touching the admin user:

```bash
imbi-api setup-clickhouse        # apply the ClickHouse schema only
imbi-api setup-permissions       # seed permissions and default roles only
imbi-api setup-service-accounts  # seed the internal service accounts only
```

All three are idempotent and safe to re-run. `setup-permissions` also refreshes
each default role's permission grants and prunes permissions retired by a
previous release; run it before `setup-service-accounts`, which grants each
account a role by name.

## Post-Setup

After setup completes, you can access Imbi at `http://localhost:8080` (or
your configured host) and log in with the admin credentials you created.

From the admin interface you can:

- Configure OAuth providers for SSO
- Create organizations and teams
- Define blueprints for custom metadata schemas
- Invite additional users
