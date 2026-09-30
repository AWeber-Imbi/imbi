# Replay comparison

This tool compares two Imbi APIs request by request: the AGE-era API
from `main` and the relational API from the integration branch. It
replaces the shadow harness of the migration plan (D14, D25; execution
plan section 6).

The tool:

1. **records** a request for each `GET` route of the OpenAPI document,
   with ids from the database (`record`);
2. runs the **write scenarios** in `scenarios/` (`scenarios`);
3. **replays** the recorded requests against a second API, and moves
   the D17 routes to their new paths (`replay`, `scenarios --path-map`);
4. **compares** status, body, and error body (`diff`);
5. gives **p50 and p95** per route for the two sides (`timings`).

`process-matrix.md` lists the processes that the replay does not
cover (the workers, the other apps, the CLI commands).

Recordings contain production data. Write them to a directory outside
the repository, and do not commit them. Use `diff --no-values` for a
report that others read.

## Files

| File | What it holds | Who changes it |
|---|---|---|
| `routes.toml` | The parameter sources (Cypher on the AGE graph) and the binding of each `GET` route | Agent F; a Wave 2 agent that adds a `GET` route |
| `owners.toml` | The agent letter of each route (execution plan section 5) | A Wave 2 agent that adds a route |
| `path-map.toml` | The D17 moves: old path to new path | The agent that moves the router |
| `normalize.toml` | The only list of fields that the diff masks, each with a reason | Agent F, the orchestrator |
| `expected/<domain>.toml` | The differences that the migration causes on purpose | The domain agent |
| `scenarios/<domain>.toml` | The write scenarios | The domain agent |
| `docker/compose.yaml` | An API on a network with no internet access | Agent F |

## Start an API for the replay

The API runs in a Linux container (the `apache-iggy` wheel does not
load on macOS), on a Docker network with no route to the internet. A
restored production copy holds production credentials, and the
background workers of the API start at once; the network keeps them
from reaching GitHub, Slack, or any other system.

1. Start a PostgreSQL container of its own for each database, with
   the database named `imbi`. The AGE-era API runs `graph.initialize()`
   at startup, which runs `CREATE EXTENSION IF NOT EXISTS pg_cron`, and
   pg_cron can only be created in the database that
   `cron.database_name` names (`imbi`). An API on a database with
   another name does not start. The API also writes to the database at
   startup, so never point it at a copy that must stay unchanged.

   ```sh
   docker run -d --name f-replay-pg -p 127.0.0.1:55433:5432 \
     -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=imbi \
     ghcr.io/aweber-imbi/postgres:latest
   ```

   For the rehearsal, restore the production copy into such a
   container (execution plan section 7). Without a copy, use the
   synthetic organization (see "Synthetic data" below).

2. Write an environment file (keep it outside the repository):

   ```sh
   IMBI_SOURCE=/Volumes/Users/gmr/Source/open-source/imbi-age-f-main
   REPLAY_DATABASE=imbi
   REPLAY_PG_PORT=55433
   REPLAY_API_PORT=18000
   IMBI_AUTH_JWT_SECRET=<a random string>
   IMBI_AUTH_ENCRYPTION_KEY=<a Fernet key>
   ```

   `IMBI_SOURCE` is a worktree of the code to run: `origin/main` for the
   old side, the integration branch for the new side. The container
   mounts it read only.

3. Install the dependencies and the embedding model into the volumes
   of the project (once for each project name):

   ```sh
   docker compose -p replay-old --env-file old.env \
     -f scripts/replay/docker/compose.yaml run --rm setup
   ```

4. Start the API. It listens on `127.0.0.1:$REPLAY_API_PORT`:

   ```sh
   docker compose -p replay-old --env-file old.env \
     -f scripts/replay/docker/compose.yaml up -d api api-relay
   ```

5. Sign a token for the first active admin user of the database, with
   the JWT secret of the API:

   ```sh
   set -a; . ./old.env; set +a
   export REPLAY_TOKEN=$(uv run python -m scripts.replay token \
     --dsn postgresql://postgres:secret@127.0.0.1:55433/imbi)
   ```

Use a second project name (`replay-new`), port, and database for the
other side. `docker compose -p <name> ... down -v` removes a side.

## Record, replay, and compare

```sh
uv run python -m scripts.replay record --repeat 2 \
  --base-url http://127.0.0.1:18000 \
  --dsn postgresql://postgres:secret@127.0.0.1:55433/imbi \
  --out ../replay-recordings/old-get

uv run python -m scripts.replay replay --repeat 2 \
  --base-url http://127.0.0.1:18001 --path-map scripts/replay/path-map.toml \
  --from ../replay-recordings/old-get --out ../replay-recordings/new-get

uv run python -m scripts.replay diff --no-values \
  --old ../replay-recordings/old-get --new ../replay-recordings/new-get \
  --json ../replay-recordings/diff.json

uv run python -m scripts.replay timings \
  --old ../replay-recordings/old-get --new ../replay-recordings/new-get
```

`record` stops when a `GET` route has no request (an *uncovered*
route). Give the route a source or a `skip` reason in `routes.toml`.
`--route` limits a run to the routes that match a glob, for example
`--route 'GET /api/organizations/{org_slug}/tags*'`.

`--repeat 2` sends each request twice. A field that is different in
the two responses is *unstable*. The diff lists each unstable field
that no rule masks, in its own section: add a rule to
`normalize.toml` with the reason, or fix the API.

`diff` exits with 1 when it finds an unexpected difference. It groups
the unexpected differences by the owner letter of the route. It also
lists each expected difference that did not occur, for the exchanges
that it compared.

### Write scenarios

Scenarios write, so run them on a database of their own (here on port
55434), not on the database of the `GET` recording. Run them against both sides with the
same run token:

```sh
uv run python -m scripts.replay scenarios \
  --base-url http://127.0.0.1:18000 \
  --dsn postgresql://postgres:secret@127.0.0.1:55434/imbi \
  --out ../replay-recordings/old-scenarios

uv run python -m scripts.replay scenarios --allow-failures \
  --base-url http://127.0.0.1:18001 --path-map scripts/replay/path-map.toml \
  --variables-from ../replay-recordings/old-scenarios \
  --out ../replay-recordings/new-scenarios
```

The new side has no graph to read the variables from, so
`--variables-from` takes them (`org_slug`, `admin_email`, `run`) from
the old recording. `--var name=value` sets one by hand.

On the old side, a step that does not return its `expect` status is a
failure, and the command exits with 1: the scenario does not describe
the AGE-era API. On the new side, use `--allow-failures`; the diff
shows the differences. A scenario can leave rows behind in the AGE
graph (see `restricted delete`), so a second run on the same database
can give other results. Use a new clone for each run.

### Synthetic data

`seed/synthetic.toml` is a scenario that creates an organization with
teams, environments, project types, tags, four projects with releases
and documents, and a second organization. Run `imbi-api setup` in the
API container first, and give the organization slug `synthetic`:

```sh
docker compose -p replay-old --env-file old.env \
  -f scripts/replay/docker/compose.yaml exec api \
  sh -c 'cd /src && uv run --frozen --no-sync imbi-api setup'
```

Then seed it:

```sh
uv run python -m scripts.replay scenarios --scenarios-dir scripts/replay/seed \
  --var org_slug=synthetic --base-url http://127.0.0.1:18000 \
  --dsn postgresql://postgres:secret@127.0.0.1:55433/imbi \
  --out ../replay-recordings/seed
```

Give `--var org_slug=synthetic` to `record` and `scenarios` as well:
the global `org_slug` is the first organization by slug, and `second`
sorts before `synthetic`.

## Add a scenario

Add a `[[scenario]]` to `scenarios/<domain>.toml`, or a new file:

```toml
domain = "tags"
owner = "J"

[[scenario]]
name = "tag lifecycle"
description = "create, read, delete"

[[scenario.step]]
name = "create"
method = "POST"
path = "/api/organizations/{org_slug}/tags/"
body = { name = "Replay Tag {run}", slug = "replay-tag-{run}" }
expect = 201
save = { tag_id = "/id" }
normalize = ["/id", "/created_at", "/updated_at"]

[[scenario.step]]
name = "delete"
method = "DELETE"
path = "/api/organizations/{org_slug}/tags/replay-tag-{run}"
expect = 204
always = true
```

Rules:

1. Write the old path. `--path-map` moves a D17 route on the new side.
2. `{org_slug}`, `{admin_email}`, and `{run}` always have a value.
   `save` adds a variable from a response (a JSON pointer).
3. `expect` is the status of the **AGE-era** API. Where the relational
   API returns another status on purpose, add an expected difference.
4. Each write is followed by a read that shows the result.
5. Include a write that must fail (409 or 422), and clean up with
   `always = true` steps.
6. A value that is new on each run (a generated id, a time) goes into
   the step's `normalize` list. Mask only the fields of that step.
7. A step for work that the API does after the response (the search
   index) uses `wait_for = { pointer = "/0/node_id", equals =
   "{project_id}", timeout = 120 }`.
8. Run `uv run pytest scripts/replay/tests`. The data-file tests check
   that each variable has a value, that each step path is a known
   route, and that each owner letter is an agent.

## Add an expected difference

Add a `[[difference]]` to `expected/<domain>.toml`:

```toml
domain = "tags"
owner = "J"

[[difference]]
key = "scenario:tags/tag lifecycle#05 *"
field = "status"
old = 201
new = 409
reason = "tags has UNIQUE (organization_id, slug)"

[[difference]]
route = "GET /api/organizations/{org_slug}/tags/{tag_slug}"
field = "body"
pointer = "/icon"
new = "<missing>"
reason = "README Not carried over: Tag.icon"
```

- `route` is a glob on the route (`METHOD template`), `key` a glob on
  the exchange key (`GET /api/...` for a recorded request,
  `scenario:<domain>/<name>#<step> ...` for a scenario step).
- `field` is `status`, `body`, or `exchange` (the request is on one
  side only).
- `pointer` is a pointer pattern for a body difference: `*` is one
  segment, `**` is zero or more. The default is every field.
- `old` and `new` are optional. When set, the value must be equal.
  `"<missing>"` is a field that is not present, `"<null>"` a null.
- `old_status` and `new_status` are optional. When set, the statuses
  of the exchange must be equal. Give them on a body entry, so that the
  entry covers only the body of that status change.
- `reason` names the source: README "Differences", "Not carried over",
  or a decision (D-number).

Each entry must name a real difference of the schema or a decision. Do
not add an entry to hide a defect: fix the code. The reviewer checks
each new entry against its reason.

## Add a GET route

Add the route to `owners.toml` with its owner letter. When its path
has a parameter other than `{org_slug}`, add a `[[route]]` to
`routes.toml` with a `source` (a Cypher query that returns the
parameter, sorted) or a `skip` reason.

## Tests

```sh
uv run pytest scripts/replay/tests
```

The tests need no database and no API.
