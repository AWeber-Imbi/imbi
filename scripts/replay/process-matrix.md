# Process matrix

The replay (`README.md`) sends HTTP requests to the API only. This
matrix lists every process that reads or writes the Imbi data, so that
the migration has a check for each one (execution plan section 6,
"Process matrix"; D14, D25).

Table 1 says what each process does today, in the AGE era (the code of
`feature/age-relational` at `5acc05a`, 2026-09-30). Table 2 has one cell for each
column of table 1. **The Wave 2 agent in the "Owner" column fills the
cells of its rows**: the name of the test or the rehearsal check that
covers the cell, or the reason that the cell does not apply. The
rehearsal (execution plan section 7, step 4) runs each check.

Paths are under `apps/api/src/imbi/api/` unless they start with
`apps/` or `libraries/`. "The graph" is the AGE graph through
`imbi.common.graph`.

## Columns

| Column | Question |
|---|---|
| Startup | What does the process do to the database when it starts? |
| Read | What does it read, and how (the graph, or the API over HTTP)? |
| Write | What does it write, and how? |
| RLS context | Which RLS context (D16) must its relational queries use, and where does the organization come from? |
| Background | Which loops, queues, and timers does it run? |
| Outbound | Which external systems does it call or write to? |
| Restart | What happens to its work when it stops and starts again? |

## Table 1: the processes today

| # | Process | Owner | Startup | Read | Write | RLS context | Background | Outbound | Restart |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `imbi-api serve`: the HTTP routes | each route's owner (`owners.toml`) | `graph.graph_lifespan` runs `graph.initialize()`: extensions `age`, `pg_cron`, `vector`, the vlabels and indexes of `graph/schemata.toml`, `public.embeddings` (`app.py`, `libraries/common/.../graph/initializer.py`). Opens ClickHouse, Iggy, Valkey, S3, SMTP, Anthropic (`lifespans.py`) | the graph, in each endpoint module | the graph, in each endpoint module; request background tasks re-embed search text (`endpoints/_search_index.py`) | organization: the `{org_slug}` path; principal only: `/users/me`, the organization switcher; none: login; instance admin: sign-in providers (README "Row-level security") | FastAPI background tasks after a response (search index, lifecycle dispatch) | ClickHouse and Iggy (operations log, events), S3 (uploads), SMTP, plugin calls (GitHub, PagerDuty, AWS, logz.io, SonarQube, Google, OIDC) | request state is lost; a background task that did not finish is lost (for example a search re-embed, until a `search-reindex`) |
| 2 | `imbi-api` startup hooks | T (plugin load), L (blueprint models) | `openapi.refresh_blueprint_models(db)` reads `Blueprint` nodes; `plugin_lifecycle.startup_load_plugins(db)` loads plugins and creates the manifest vlabels at runtime (`lifespans.py:34-48`, `plugins/lifecycle.py`, `libraries/common/.../plugins/schemas.py:180`) | `Blueprint`, `PluginRegistration` | manifest labels (AGE DDL) and plugin registrations | Blueprints are organization rows (D17): no organization is known at startup | none | none | runs again at each start; idempotent |
| 3 | identity refresh sweeper | M | starts when Valkey and the graph are up (`lifespans.py:114`) | `IdentityConnection` rows that expire within 300 s (`identity/sweeper.py`, `identity/repository.py`) | new tokens, or `status='expired'`, on `IdentityConnection` | the organization of the row: `identity_connections.organization_id` (README "Row-level security") | every 60 s, with a Valkey lock of 60 s for each connection (`identity/sweeper.py:27-32`) | OAuth token endpoints of the identity providers (GitHub, Google, OIDC) | stateless; the next poll finds the same rows |
| 4 | document read-session sweeper | Q | starts when Valkey is up (`lifespans.py:150`) | open read sessions in Valkey (`documents/read_sweeper.py`) | closes sessions; engaged time goes to the document numbers (`endpoints/_document_reads.py`) | organization of the document; to verify: does it write organization rows? | every 60 s (`documents/read_sweeper.py:24`) | Iggy / ClickHouse (`document_read_*` topics) | sessions stay in Valkey; the next sweep closes them |
| 5 | commit-sync worker | N | Valkey consumer (`lifespans.py:184`) | `Project`, `Release`, integration credentials (`commit_sync/service.py`) | commits and tags; `Release` rows | organization of the queued project | Valkey queue, 10 s debounce, rate-limit pause (`commit_sync/queue.py:35-49`) | GitHub (commit and tag APIs); ClickHouse `commits`, `tags` | the queue survives in Valkey; a claimed item that did not finish is claimed again (to verify) |
| 6 | pr-sync worker | N | Valkey consumer (`lifespans.py:217`) | `Project`, integration credentials (`pr_sync/service.py`) | pull request state | organization of the queued project | Valkey queue, 10 s debounce (`pr_sync/queue.py:36-41`) | GitHub pull request API; ClickHouse `pull_requests` | as row 5 |
| 7 | deployment-sync worker | O | Valkey consumer (`lifespans.py:250`) | `Project`, `Release`, `Deployment`, `Environment` (`deployment_sync/`) | `Deployment` rows and their status | organization of the queued project | Valkey queue, 10 s debounce, 30 s claim renew (`deployment_sync/queue.py:37-46`) | GitHub deployments API; operations log | claim renew; an item whose claim expired is taken again |
| 8 | release-promote worker | N | Valkey consumer (`lifespans.py:287`) | `Release`, `Project` (`release_promote/`) | release promotion state (`project_promotions`) | organization of the queued project | Valkey queue, 30 s claim renew, 0.5 s idle sleep (`release_promote/queue.py:53-62`) | GitHub workflow dispatch and runs | as row 7 |
| 9 | maintenance worker | U (operations), the owner of each operation | Valkey consumer (`lifespans.py:324`) | depends on the operation (`maintenance/registry.py`: run-analysis, remediate, sync-fixes, rescore, deployment-resync, deployment-sweep, deployment-status-repair, commit-pushed-at-check/repair, opslog-backfill, orphan-release-check/purge, commit-sync, pr-sync, search-reindex) | depends on the operation | an operation runs for all projects, so it needs a loop over organizations, or an organization for each item | polls every 2 s (`maintenance/worker.py:25`) | GitHub, PagerDuty, SonarQube (analysis and remediation); ClickHouse `maintenance_log`; Iggy | a running operation is lost at stop (to verify: resume or rerun) |
| 10 | score worker and daily tick | L | Valkey consumer and a timer (`lifespans.py:357`) | `Project`, `ScoringPolicy`, blueprint attributes (`scoring/`) | the project score; ClickHouse `score_history` | organization of the project | queue with 5 s debounce; daily tick at 06:00 UTC, polled each 3600 s (`scoring/queue.py:47-52`) | ClickHouse (through Iggy) | the tick runs again after a restart if the day was not scored (to verify) |
| 11 | `imbi-assistant serve` | S | `graph.graph_lifespan` (`apps/assistant/.../app.py:81`); connects to the enabled `MCPServer` nodes (`apps/assistant/.../external_mcp.py`) | `Conversation`, `Message`, `MCPServer` (`apps/assistant/.../age_ops.py`) | conversations and messages (`age_ops.py:37-220`) | conversations: principal only, with `owner_only` (README); the conversation routes move under the organization (D17, WP1.10). `MCPServer` is an organization table, but startup has no organization | none found | Anthropic; the external MCP servers; the imbi MCP tools (HTTP to the API) | conversations are in the database; MCP connections are made again at start |
| 12 | `imbi-gateway serve` | R | `graph.graph_lifespan`, ClickHouse, Iggy (`apps/gateway/.../app.py:37-41`) | `Webhook`, `WebhookRule`, `Integration` by webhook id, then the `Project` (`apps/gateway/.../notifications.py:209,548`) | through the API (`apps/gateway/.../actions.py`, `ImbiClient`); no graph write found | none, then organization: `webhook_organization_id(text)` gives the organization for `POST /notifications/{id}` (README "Row-level security") | none | the plugin actions of the rules (GitHub, PagerDuty, SonarQube); Iggy `events` (`gateway`) | stateless; a webhook delivery that failed is sent again by its sender |
| 13 | `imbi-scheduler serve` | O (`store/`) | `graph.graph_lifespan` for the auth of the `/tasks` routes; `store.store_lifespan` creates the `scheduler` schema (`apps/scheduler/.../app.py:26-31`, `store/initializer.py`) | the graph for permissions only; its own tables in the `scheduler` schema | its own tables; the tasks call the API over HTTP with a client credential (`apps/scheduler/.../executor.py`) | the service account membership of `imbi-scheduler` (`auth/internal_services.py`) | the trigger loop (`apps/scheduler/.../engine.py`, `triggers.py`) | the API over HTTP; ClickHouse `scheduler_runs` (Iggy) | the store keeps the tasks; the engine starts the triggers again |
| 14 | `imbi-slackbot serve` | M (`identity.py`) | `graph.graph_lifespan` (`apps/slackbot/.../app.py:69`) | `User` by email, to sign a token (`apps/slackbot/.../identity.py:34,89`) | none found; tools call the API over HTTP with that token | principal only (the user); the tools carry the organization | the Slack socket or events handler | Slack; Anthropic; the imbi MCP tools (HTTP to the API) | stateless; the in-flight replies are lost |
| 15 | `imbi-mcp` | S | none: it reads `openapi.json` of the API (`apps/mcp/.../server.py:125`) | the API over HTTP | the API over HTTP | the token of the caller | none | the API only | stateless |
| 16 | `imbi-api setup` | K (organization), M (seed) | opens the graph and ClickHouse (`entrypoint.py:238`) | `Organization`, `User` | organization, permissions, roles, the admin user and its `MEMBER_OF`, the internal service accounts, the ClickHouse schema | instance admin and the new organization (a seed runs before any membership exists) | none | ClickHouse DDL | idempotent except the admin user (it asks) |
| 17 | `imbi-api setup-postgres` | V | `graph.initialize()` (`entrypoint.py:60`) | the catalog | AGE graph DDL | none | none | none | idempotent; D10 removes it (the schema comes from `pglifecycle deploy`) |
| 18 | `imbi-api setup-permissions` | M | opens the graph (`entrypoint.py:85`) | `Permission`, `Role` | prunes retired permissions, seeds permissions and default roles (`auth/seed.py`) | instance (permissions); roles are organization rows | none | none | idempotent |
| 19 | `imbi-api setup-service-accounts` | K | opens the graph (`entrypoint.py:128`) | the only `Organization` | the `imbi-scheduler` and `imbi-gateway` service accounts and credentials (`auth/internal_services.py`) | instance (service accounts) and the membership in one organization | none | none | idempotent; a credential is never rotated |
| 20 | `imbi-api setup-clickhouse` | none (no graph) | ClickHouse only (`entrypoint.py:18`) | none | ClickHouse DDL | not applicable | none | ClickHouse | idempotent |
| 21 | `imbi-common` CLI (`etl audit`, the ETL load, `etl reconcile`) | D (ETL, reconcile), E (audit) | new in this migration; no console script exists in `libraries/common/pyproject.toml` today | the graph with plain SQL (audit, ETL) and the relational tables (reconcile) | the relational tables (ETL), as `imbi_maintenance` | `imbi_maintenance` (BYPASSRLS), never the application login (D16) | none | none | the ETL is one TRUNCATE and INSERT in the freeze (D20); a failed load runs again from the start |

## Table 2: covered by

Each cell names a test (module and test case) or a rehearsal check,
or says why the cell does not apply. The owner letter is in each cell
until the owner fills it.

| # | Process | Startup | Read | Write | RLS context | Background | Outbound | Restart |
|---|---|---|---|---|---|---|---|---|
| 1 | `imbi-api serve` | V: | replay `record`/`replay` (all `GET` routes) | replay `scenarios` | each owner: the isolation matrix (recipe step 5) | each owner: | each owner: | V: |
| 2 | startup hooks | T: | L: | T: | L, T: | not applicable | not applicable | T: |
| 3 | identity refresh sweeper | M: | M: | M: | M: | M: | M: | M: |
| 4 | document read sweeper | Q: | Q: | Q: | Q: | Q: | Q: | Q: |
| 5 | commit-sync worker | N: | N: | N: | N: | N: | N: | N: |
| 6 | pr-sync worker | N: | N: | N: | N: | N: | N: | N: |
| 7 | deployment-sync worker | O: | O: | O: | O: | O: | O: | O: |
| 8 | release-promote worker | N: | N: | N: | N: | N: | N: | N: |
| 9 | maintenance worker | U: | U: | U: | U: | U: | U: | U: |
| 10 | score worker and tick | L: | L: | L: | L: | L: | L: | L: |
| 11 | `imbi-assistant` | S: | S: | S: | S: | S: | S: | S: |
| 12 | `imbi-gateway` | R: | R: | R: | R: | not applicable | R: | R: |
| 13 | `imbi-scheduler` | O: | O: | O: | O: | O: | O: | O: |
| 14 | `imbi-slackbot` | M: | M: | not applicable (API) | M: | M: | M: | M: |
| 15 | `imbi-mcp` | not applicable (no database) | replay (API) | replay (API) | not applicable (the API does it) | not applicable | not applicable | not applicable |
| 16 | `imbi-api setup` | K, M: | K, M: | K, M: | K, M: | not applicable | not applicable | K, M: |
| 17 | `imbi-api setup-postgres` | V: | not applicable | V: | not applicable | not applicable | not applicable | V: |
| 18 | `imbi-api setup-permissions` | M: | M: | M: | M: | not applicable | not applicable | M: |
| 19 | `imbi-api setup-service-accounts` | K: | K: | K: | K: | not applicable | not applicable | K: |
| 20 | `imbi-api setup-clickhouse` | not applicable (no Postgres) | not applicable | not applicable | not applicable | not applicable | not applicable | not applicable |
| 21 | `imbi-common` ETL CLI | D, E: | D, E: | D: | D: | not applicable | not applicable | D: |

## Open points for the owners

1. **Row 2 and row 11:** `Blueprint` and `MCPServer` become organization
   rows (D17, Open question 1 of `schemata/README.md`). The API startup
   (blueprint models) and the assistant startup (external MCP
   connections) have no organization. The owners (L, S) must say which
   RLS context these reads use: a loop over organizations, or a
   SECURITY DEFINER lookup. The README does not list one today.
2. **Row 9:** each maintenance operation runs over all projects. It
   needs an organization for each project (one transaction for each
   organization), not one context for the whole run.
3. **Rows 5 to 10:** a Valkey queue item holds a project id. After the
   cutover the worker needs the organization of that project before
   its first query. The item can carry the organization, or the worker
   can use a lookup function.
4. **Row 1:** the replay shows the API routes only. The request
   background tasks (search re-embed, lifecycle dispatch) are covered
   by the search scenario (`scenarios/search.toml`) and by the owners'
   tests.
