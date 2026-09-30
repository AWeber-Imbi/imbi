# ADR 0020: Replace Apache AGE with Relational PostgreSQL

Date: 2026-09-30

## Status

Accepted

This ADR records the decision to move every domain entity out of the
Apache AGE graph and into relational PostgreSQL tables, and the rules
for that move.

## Context

No ADR decided on AGE. The one written reason is in `docs/api/index.md`:
one database for graph and relational data. The codebase does not use a
graph feature that SQL does not have. An AST walk found about 500 Cypher
statements. One statement has a variable-length path (role
inheritance), and a recursive CTE replaces it. All other statements are
lookups, fixed joins, aggregations, and writes.

AGE has a continuous cost:

- **Silent wrong answers.** AGE drops `ORDER BY` before an aggregation,
  `*0..` does not match the start node, `LIMIT` after `UNWIND` stops the
  writes, `SET` on an edge map can do nothing, and `collect()` of a null
  map gives `[{}]`. Each of these shipped, and each has a workaround and
  a test.
- **Concurrency.** AGE has no EvalPlanQual pass. A concurrent update
  fails the statement, so the code retries every graph call. AGE 1.7.0
  corrupts a backend's label cache under concurrent `MERGE` and
  `DELETE` (Sentry IMBI-4M).
- **Constraints.** AGE cannot enforce a composite unique key. The
  application enforced `(project, tag)` on Releases, and production got
  1,076 duplicate groups.
- **Query construction.** `cypher()` takes no bind parameters. The code
  renders each value as a Cypher literal by hand, and two bugs came from
  that layer. Results come back as `agtype` text that `parse_agtype`
  decodes at hundreds of call sites.
- **Operations.** A custom PostgreSQL image is necessary, and managed
  PostgreSQL is not possible. A restore needs about 180 lines of
  `ag_catalog` repair. There is no statement to rename a label.

Data already left the graph for these reasons: embeddings (pgvector),
the scheduler tables, and the SBOM usage facts (ClickHouse).

The reasoning and the measurements are in the Imbi meta repository at
`docs/age-to-relational-evaluation.md`. The schema of record is
`schemata/README.md` in this repository. The work packages are in the
meta repository at `docs/age-to-relational-implementation-plan.md` and
`docs/age-to-relational-execution-plan.md`.

## Decision

Imbi replaces the AGE graph with a relational schema in PostgreSQL. The
decisions below are locked. The implementation plan (section 2) and the
execution plan (section 1) have the full text of each one.

### Scope and schema

| # | Decision |
|---|---|
| D1 | Every domain entity moves to relational tables. pgvector and ClickHouse stay. pg_cron is not part of the schema. |
| D2 | One coordinated cutover for all domains. No domain changes its store alone. |
| D3 | The nanoid `id` text stays the primary key of every entity. No UUIDs. The exception: `document_templates` get new ids, because their graph id is the slug. |
| D4 | `tenants` and `organizations` tables. Each organization table has `organization_id` (NOT NULL, except in `integrations`), composite `(organization_id, x_id)` foreign keys, and FORCE row-level security. Organization slugs are unique for the instance. |
| D5 | A `principals` supertype over `users` and `service_accounts`, both instance tables. Access to an organization comes only from `memberships`. |
| D6 | No global entity registry. A document has three nullable references and a check that allows at most one. Documents and templates have tags. Projects have no tags. |
| D7 | `CAN_ACCESS` keeps `(resource_type, resource_slug)`, in `resource_acls`. |
| D8 | Plugin data goes into `plugin_entities` and `plugin_edges` with JSONB payloads. Manifest keys are rows in `plugin_entity_keys`. The application creates no indexes at runtime. |
| D9 | One `attributes` JSONB object column for each blueprint table. No GIN index. A generated column with a btree index is added for an attribute that lists filter or sort on often. |
| D10 | The schema is the pglifecycle project at `schemata/`. Changes reach a database only through `pglifecycle deploy`, never at application startup. No Alembic, no ORM, no migration files. Automation never uses `--allow-drop`. Before the cutover, `deploy` runs only against new databases. The cutover is the first deploy into production. |
| D15 | No ORM and no generic SQL generator: psycopg 3, `psycopg.sql` composables, bind parameters, and hand-written SQL for each repository. |

### Tenancy and access

| # | Decision |
|---|---|
| D16 | Four RLS contexts: organization, principal only, none, and instance admin (the `imbi_admin` login in its own pool). Lookups before an organization is known use SECURITY DEFINER functions. `imbi_maintenance` (BYPASSRLS) is only for the ETL, the reconciliation, and catalog cleanup. |
| D17 | The routes that read organization tables move under `/organizations/{org_slug}`: `/roles`, `/blueprints`, `/scoring/policies`, `/mcp-servers`, the plugin entity routes, `POST /uploads`, and the assistant conversation routes. |
| D18 | Organization, team, environment, and project type deletes are RESTRICT. SQLSTATE 23001 and 23503 on a delete give 409. A user or service account delete removes the principal and its credentials. Content stays. Delete triggers remove embeddings. |
| D19 | The SBOM catalog is shared. `imbi_app` can only insert into it, and the first writer wins. Other values go to overrides for each organization. Governance marks, notes, and advisory links are for each organization. |
| D21 | Organization-owned login providers are dropped. Only the instance sign-in provider can have `used_as_login`. |
| D22 | Authentication does not load identity connections. The project list reads the user's `github-enterprise-cloud` subject in its organization context. |
| D23 | Search does not embed `Component` or `Role`. Every `embeddings` row has an organization. |

### Migration and cutover

| # | Decision |
|---|---|
| D11 | Tests convert with the code. Test databases come from templates. |
| D12 | The duplicate Release groups are gone (#277). The schema has the unique indexes. The audit asserts zero duplicates before the ETL. |
| D13 | The Cypher workbench is audited. If it stays, it becomes a read-only SQL console outside the LLM toolset. |
| D14 | Each table has a reconciliation query, and each endpoint has a list of expected differences. The replay comparison (D25) is the gate. |
| D20 | The cutover load is TRUNCATE plus plain INSERT, in foreign key order, as `imbi_maintenance`, inside the write freeze. No upsert and no delta load. |
| D24 | For the cutover and the releases after it, the release workflow prints the production DDL plan, and an operator applies it with `psql -1` after review. A later work package adds a Helm `pre-upgrade` hook Job. |
| D25 | Replace in place. Each domain work package deletes its Cypher and writes SQL. There is no second implementation and no store switch. The replay comparison and the process matrix replace the shadow harness. The rollback is the previous release image. |
| D26 | All work merges into the integration branch `feature/age-relational`. One PR from that branch goes into `main`. |
| D27 | pglifecycle is pinned to one commit of `main` until a release is tagged. CI, the rehearsal, and the cutover use the same build. The runbook records its SHA-256. |
| D28 | The write freeze stops every app. A maintenance page shows from the freeze to the validation. The new image has a read-only switch for the validation step only. |
| D29 | The recommendations of O1, O2, O7, O9, O10, and O11 are accepted (see below). O3 to O6 wait for the audit counts. |
| D30 | These work packages come after the cutover: other stores gain the organization (WP3.4; the cutover still flushes Valkey), the backup and restore drill (WP3.5), the AGE drop (WP4.2), the parts of the graph library removal that the branch does not do (WP4.3), and the documentation update (WP4.4). |

### Accepted open decisions (D29)

| # | Decision |
|---|---|
| O1 | No reverse ETL. The cutover does not change AGE. The point of no return is the first write to the relational tables. Before it, the rollback starts the previous release image. After it, only forward fixes are possible. |
| O2 | The ETL assigns the rows that have no organization today to the one production organization. The audit blocks the ETL when production has more than one organization. |
| O7 | A capability identity pin is RESTRICT when its integration is deleted, not SET NULL. |
| O9 | `/admin/dashboard` counts rows through a SECURITY DEFINER function that returns only the counts. |
| O10 | The ETL skips the Releases that no Project owns, and the reconciliation report lists them. |
| O11 | The `updated_at` trigger of the five profile and credential tables lists its columns (`update_columns`), so an automatic write (sign-in, token exchange, API key use) does not change `updated_at`. |

## Consequences

- The graph library, `parse_agtype`, the retry wrappers, and the
  label-cache workaround go away. SQL constraints enforce uniqueness and
  tenancy.
- Row-level security isolates organizations in the database. It
  protects against a query that omits the organization condition. It
  does not protect against SQL injection on the `imbi_app` connection.
- Some routes move under `/organizations/{org_slug}` (D17). The UI, the
  MCP tools, and API clients that use these routes change.
- Some deletes that cascade in the graph fail with 409 (D18).
- The cutover is one event with a write freeze and a maintenance page.
  Before the first relational write, the rollback starts the previous
  image. After it, a defect needs a forward fix.
- pglifecycle becomes a build dependency. Common ADR 0004 records how
  schema changes ship.
- The AGE extension stays in production for a window after the cutover.
  WP4.2 drops it. Then Imbi can use a PostgreSQL image with pgvector
  only, or a managed service that has pgvector.

## Alternatives considered

- **Keep AGE and upgrade to 1.8.0.** Upgrade the extension in the
  PostgreSQL image, run `ALTER EXTENSION age UPDATE` in production, and
  pin the version. This fixes only the label-cache corruption. All other
  costs in the Context stay, and data continues to leave the graph one
  incident at a time.
- **Two implementations behind a store switch** (the first version of
  the implementation plan). Each domain gets an AGE and a relational
  repository, and a setting selects one. Rejected (D25): it doubles the
  code of each domain, and the second implementation is deleted after
  the cutover. The previous image already has the AGE code for a
  rollback.
- **A repeated upsert with a final delta load** (the evaluation).
  Rejected (D20, schema review F4): the tables have no foreign key
  cycles, so one TRUNCATE and INSERT in foreign key order inside the
  freeze loads them. There is no delta to find.
- **A reverse ETL for the rollback** (the evaluation). Rejected (O1): it
  needs a mapping back into the graph for each of 74 tables, and the
  writes after the cutover cannot be found, because nothing records
  deletes.
