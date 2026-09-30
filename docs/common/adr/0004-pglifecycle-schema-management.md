# 4. Manage the relational schema with pglifecycle

Date: 2026-09-30

## Status

Proposed

## Context

API ADR 0020 moves every domain entity from the Apache AGE graph into
relational PostgreSQL tables. Those tables need one schema of record and
one way to change a database so that it matches that schema.

Today, each app makes its own database objects at startup.
`graph_lifespan()` runs `graph.initialize()` in the api, assistant,
gateway, scheduler, and slackbot apps, and the `imbi-api setup-postgres`
command runs it too. It creates the `age`, `pg_cron`, and `vector`
extensions, the legacy `public.embeddings` table, and
`public.embedding_distance(agtype, ...)`. The scheduler has its own
declarative `schemata.toml` and an initializer for the `scheduler`
schema.

[pglifecycle](https://gmr.github.io/pglifecycle/) keeps a schema as a
project with one YAML file for each database object. `build` validates
the project. `deploy` compares the project with a live database and
prints the DDL that makes the database match. `deploy --apply` runs
that DDL in one transaction. There are no migration files.

## Decision

### The schema of record

The schema of record is the pglifecycle project at `schemata/`. Its
`README.md` holds the design: the tables, the roles, row-level security,
the delete behavior, and the known problems.

The application never creates relational tables at startup. A change
reaches a database only through `pglifecycle deploy`, as a deployment
step.

- The scheduler's `schemata.toml` initializer moves into the project in
  WP2.4 (execution plan agent O).
- The integration branch deletes the graph initializer and
  `graph_lifespan()` before the cutover (execution plan Wave 3, agent
  V). The first relational release does not run it.

### How a change ships

1. Edit the YAML in `schemata/` by hand. Write each expression (CHECK,
   index WHERE, trigger WHEN, policy, function body) in the form that
   PostgreSQL returns. README "Conventions", item "Expressions", tells
   how. If the form is different, each deploy shows a change.
2. CI runs `moon run root:schema-check`. The task builds the project,
   applies it to a new database, and checks that a second deploy gives
   only the statements in `schemata/tests/second-deploy-allowlist.sql`.
   Then it runs the SQL tests. CI shows the plan on the PR.
3. After the cutover, the release workflow prints the plan for
   production. An operator reviews the plan and applies it with
   `psql -1` before the new image rolls out (D24). `release.yml` has no
   deploy job today.

Automation never uses `--allow-drop`. A person applies a destructive
change from the printed plan.

A later work package adds a Helm `pre-upgrade` hook Job that runs
`pglifecycle deploy --apply`. `--apply` refuses destructive statements.
Then every operator of the chart gets schema upgrades. That work
package also adds a `helm template` check to CI, because nothing
renders the chart in CI today. The hook has these conditions:

- A second deploy is empty. While README Known problem 2 remains (the
  HNSW index), each deploy has a `DROP INDEX`, and `--apply` refuses it.
- The pglifecycle build is pinned (see below).
- The Job does not retry automatically.
- A schema change is additive until the release after the code that
  stops using the old form (expand, then contract). The old pods then
  continue to work if the upgrade fails after the hook.

### No deploy into a live database before the cutover

Before the cutover, no job deploys into a database where an AGE-era app
runs (D10): production, a restored production copy, or the dev
environment after `just sync-prod-to-dev`.

Reason: the live `public` schema has the legacy `public.embeddings`
table and `public.embedding_distance`. `deploy` would alter that table
(row-level security on it stops the AGE-era search), or propose to drop
the function. `-T` does not prevent this. It removes a table only from
the database side of the comparison, so the project side still creates
it.

The cutover runbook (WP0.8) moves the legacy table into a `legacy`
schema first. The cutover is the first deploy into production.

### Statements that cannot run in one transaction

`CREATE INDEX CONCURRENTLY` and `ALTER TYPE ... ADD VALUE` cannot run
under `psql -1` or `deploy --apply`.

- Add a new index on a large table while the table is still empty or
  small (before the cutover). A plain `CREATE INDEX` is then acceptable.
- The schema uses no enum types. Enumerations are TEXT columns with a
  named CHECK (README "Conventions").
- Any other statement of this kind is a manual step in the runbook.

### Objects that the project does not manage

While the graph, the scheduler tables, and pg_cron stay in the same
database, `deploy` runs with these flags, so that it does not propose to
drop them:

```
-N imbi -N ag_catalog -N scheduler --exclude-extension age --exclude-extension pg_cron
```

- WP2.4 removes `-N scheduler`, when the scheduler tables move into the
  project.
- The cutover PR adds `-N legacy` (WP0.8, step 6).
- WP4.2 removes the `age`, `pg_cron`, and `legacy` flags, after the
  AGE window. A person applies that plan with `--allow-drop`.

### Roles and owners

`deploy` applies grants. It does not create roles:
`schemata/scripts/create-roles.sql` creates them before the first
deploy (WP0.4).

`deploy` sets the owner that each YAML file names. pglifecycle `main`
does this from commit `47c58cc` (2026-09-29). An earlier build created
each object as the connecting role. WP0.4 confirmed the behavior at the
pinned commit `4f6729c` (PR #348). So `schemata/scripts/set-owners.sql`
is a check: it changes nothing, and it fails when an owner is not the
owner that README "Roles" names. The check matters most for the
SECURITY DEFINER functions: a function that the deploying superuser
owns runs as superuser.

### The pglifecycle pin

No pglifecycle release has the features that the schema needs. The
latest release is 2.0.0-alpha.2. So, until Gavin tags a release (D27):

- CI and the moon tasks build pglifecycle from one commit of `main`.
  Agent A pins the head of `main` when WP0.4 starts (`4f6729c` on
  2026-09-30) if `root:schema-check` passes with it, and records the
  commit in `schemata/README.md`.
- The rehearsal and the cutover use the same build as CI. The runbook
  records the SHA-256 of the binary.
- When a release is tagged, a PR changes the pin to the release, in
  `.prototools` or the moon task and in the GitHub Action `version:`
  input. If the release fixes README Known problem 2, the same PR
  removes the HNSW statements from the second-deploy allowlist.

`main` moves, and alpha releases move. The pin does not.

## Consequences

- One project holds every relational object. A review of the YAML is a
  review of the schema.
- An app start does not change the schema. A schema change is a
  deployment step with a reviewed plan.
- The same pglifecycle build runs in CI, in the rehearsal, and in the
  cutover.
- The CI check needs the Imbi PostgreSQL image, because the schema uses
  pgvector and the tests use pgTAP.
- A pglifecycle defect can block a schema change. The project then waits
  for a pglifecycle fix, or a person applies a reviewed manual step.
- Until the Helm hook exists, every schema change after the cutover
  needs an operator.
