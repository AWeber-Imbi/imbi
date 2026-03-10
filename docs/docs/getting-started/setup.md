# Initial Setup

After installing Imbi and configuring the environment, you need to run
the setup command to initialize the authentication system and create
your first admin user.

## Running Setup

### Docker

```bash
docker run -it \
  -e NEO4J_URL=bolt://neo4j:7687 \
  -e CLICKHOUSE_URL=http://default:password@clickhouse:8123/imbi \
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

The setup command is idempotent: it checks whether the system has already
been seeded before making changes, so it is safe to run multiple times.

## Post-Setup

After setup completes, you can access Imbi at `http://localhost:8080` (or
your configured host) and log in with the admin credentials you created.

From the admin interface you can:

- Configure OAuth providers for SSO
- Create organizations and teams
- Define blueprints for custom metadata schemas
- Invite additional users
