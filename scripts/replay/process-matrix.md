# Process matrix

The replay (`README.md`) sends HTTP requests to the API only. This
matrix lists every process that reads or writes the Imbi data, so that
the migration has a check for each one (execution plan section 6,
"Process matrix"; D14, D25).

Table 1 says what each process does today, in the AGE era (the code of
`feature/age-relational` on 2026-09-30). Table 2 has one cell for each
column of table 1. **The Wave 2 agent in the "Owner" column fills the
cells of its rows**: the name of the test or the rehearsal check that
covers the cell, or the reason that the cell does not apply. The
rehearsal (execution plan section 7, step 4) runs each check.

Paths: `A/` is `apps/api/src/imbi/api/`, `C/` is
`libraries/common/src/imbi/common/`, `G/` is `C/graph/`. Other paths
start at the repository root. "The graph" is the AGE graph through
`imbi.common.graph`.

## Columns

| Column | Question |
|---|---|
| Startup | What does the process do to the stores when it starts? |
| Read | What does it read, and how (the graph, or the API over HTTP)? |
| Write | What does it write, and how? |
| RLS context | Where does the organization of its data come from today, and so which RLS context (D16) must its relational queries use? |
| Background | Which loops, queues, and timers does it run? |
| Outbound | Which external systems does it call or write to? |
| Restart | What happens to its work when it stops and starts again? |

## Table 1: the processes today

| # | Process | Owner | Startup | Read | Write | RLS context | Background | Outbound | Restart |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `imbi-api serve`: the HTTP routes | each route's owner (`owners.toml`) | lifespan order at `A/app.py:22-39`: Sentry, ClickHouse (raises on failure, `A/lifespans.py:52-58`), Iggy (connects and creates the topics, `:62-68`), `graph.graph_lifespan` (`G/__init__.py:30-39`: `initialize()` creates the extensions `age`, `pg_cron`, `vector`, the graph, the vlabels, the indexes, `public.embeddings`, and functions; then rows 2 and 3), SMTP, S3 (creates the bucket), Anthropic, Valkey, then rows 4 to 11 | the graph, in each endpoint module, for example the project list (`A/endpoints/projects.py:2209`) | the graph, for example `CREATE (p:Project)` (`A/endpoints/projects.py:1778`) | organization: the `/organizations/{org_slug}` path (`A/endpoints/organizations.py:63`); principal only: `/users/me` and the organization switcher; none: sign-in; instance admin: the sign-in providers (`schemata/README.md`, "Row-level security"). Today the permissions are the union over all memberships (`C/auth/permissions.py:294-305`); only the path slug separates organizations | FastAPI background tasks after a response, for example the search index (`A/endpoints/projects.py:1975`, `A/endpoints/releases.py:866`, `A/endpoints/comments.py:514`) | plugins (GitHub, PagerDuty, SonarQube, AWS, logz.io, Google, OIDC); SMTP (`A/email/client.py:35-58`); S3 (`A/storage/client.py:41-69`); Anthropic; OAuth identity providers (`A/auth/oauth.py:149`); ClickHouse queries; Iggy (`operations_log`, `events`, `document_versions`, `email_audit`, and others) | the startup steps run again and are idempotent; background tasks that did not finish are lost |
| 2 | blueprint models (`A/openapi.py:222`) | L | runs from `_on_graph_startup` (`A/lifespans.py:34-48`) and after each blueprint edit (`A/endpoints/blueprints.py:107,291,344`) | `db.match(Blueprint)` (`C/blueprints.py:234,272`) | none: it builds the models in the process | global today; `blueprints` is an organization table (D17) and startup has no organization | none | none | built again on each pod at start; a failure is only logged; other pods do not see an edit until they restart |
| 3 | plugin load (`A/plugins/lifecycle.py:17`) | T | loads the plugins, applies the manifest vlabels and indexes (`C/plugins/schemas.py:118-210`), seeds the registrations, runs the audits (`A/plugins/schemas.py:26`) | `MATCH (i:Integration)` (`A/plugins/lifecycle.py:46-50`) | `MERGE PluginRegistration`, `SET enabled = coalesce(...)` (`A/plugins/lifecycle.py:76-86`); AGE DDL for the manifest labels | global (`plugin_registrations` is an instance table) | none; the cross-pod reload (`A/plugins/reload.py:135`) is not in the lifespan list | none | idempotent; a schema failure is logged and startup continues (`A/lifespans.py:42-45`) |
| 4 | identity refresh sweeper (`A/identity/sweeper.py:166`) | M | starts when Valkey and the graph are up (`A/lifespans.py:114`) | active `IdentityConnection` rows that expire soon (`A/identity/repository.py:509-526`) | `SET status='expired'` (`A/identity/repository.py:242-250`); token upsert (`:72-136`); orphan delete (`A/identity/sweeper.py:83`) | none today, keyed by (integration, user); relational: the organization of the row (`identity_connections.organization_id`) | every 60 s; a Valkey lock of 60 s for each connection (`A/identity/sweeper.py:27-46`) | identity provider token refresh through the plugin (`A/identity/flows.py:336-368`) | stateless; the next poll finds the same rows |
| 5 | document read-session sweeper (`A/documents/read_sweeper.py:65`) | Q | starts when Valkey is up (`A/lifespans.py:150`) | no graph: Valkey and ClickHouse (`A/endpoints/_document_reads.py:412`) | no graph: Iggy `document_read_sessions` (`A/endpoints/_document_reads.py:304-356`) | the `org_slug` of the ClickHouse row | every 60 s, with a Valkey lock for each round (`A/documents/read_sweeper.py:24-46`) | ClickHouse, Iggy | idempotent (deduplicated on the session id) |
| 6 | commit-sync worker (`A/commit_sync/queue.py`) | N | `XGROUP CREATE` (`A/commit_sync/queue.py:92-98`) | capability resolution (`A/plugins/resolution.py:106`, `A/plugins/assignments.py:127`); status (`A/commit_sync/service.py:367-375`) | `SET p.commit_sync_status` (`A/commit_sync/service.py:281-323`) | the `org_slug` of the stream entry (`A/commit_sync/queue.py:75,103`) | stream `imbi:commit-sync`, 2 s block, 10 s debounce, 120 s reclaim, dead-letter after 3 deliveries, pause key (`A/commit_sync/queue.py:30-47`) | GitHub; ClickHouse; Iggy `commits`, `tags` (`plugins/github/.../commits.py`) | entries are reclaimed after 120 s; a status can stay `running` until the job runs again |
| 7 | pr-sync worker (`A/pr_sync/queue.py`) | N | consumer group (`A/pr_sync/queue.py:78`) | capability resolution; status (`A/pr_sync/service.py:224-231`) | `SET p.pr_sync_status` (`A/pr_sync/service.py:161-180`) | the `org_slug` of the stream entry (`A/pr_sync/queue.py:87-97`) | stream `imbi:pr-sync`, as row 6 (`A/pr_sync/queue.py:31-41`) | GitHub; Iggy `pull_requests` | as row 6 |
| 8 | deployment-sync worker (`A/deployment_sync/queue.py`) | O | consumer group (`A/deployment_sync/queue.py:94`) | `resync_for_project` (`A/endpoints/project_deployments.py:1743-1790`); status (`A/deployment_sync/service.py:218-234`) | deployment `MERGE` and `DEPLOYED_IN` (`A/endpoints/releases.py:1455-1630`); release upsert (`A/endpoints/project_deployments.py:4410`); status (`A/deployment_sync/service.py:109-177`) | the `org_slug` of the stream entry (`A/deployment_sync/queue.py:111-113`) | stream `imbi:deployment-sync`, 2 s block, 10 s debounce, 120 s reclaim, 30 s claim renewal, dead-letter after 3 deliveries (`A/deployment_sync/queue.py:32-46,251`) | deploy providers through the plugin | idempotent through the `external_run_id` merge (`A/endpoints/releases.py:1498-1502`) |
| 9 | release-promote worker (`A/release_promote/queue.py`) | N | consumer group (`A/release_promote/queue.py:91`) | `p.promote_*` (`A/release_promote/service.py:216-229`) | `SET p.promote_*` (`A/release_promote/service.py:122-159`); a deployment on completion; `close_in_flight` on abandon (`C/deployments.py:797`) | `WatchJob.org_slug` (`A/release_promote/service.py:273-284`) | stream `imbi:release-promote`, 8 jobs at once, 30 s claim renewal (`A/release_promote/queue.py:45-62`); polls every 10 to 30 s, 45 minute timeout (`A/release_promote/service.py:50-60`) | GitHub Actions run polling; tag resync; rollout watch | polls the same run id again, so idempotent (`A/release_promote/queue.py:6-9`) |
| 10 | maintenance worker (`A/maintenance/worker.py:212`) | U (operations), and the owner of each operation | starts when Valkey and the graph are up (`A/lifespans.py:324`); a run starts from the admin endpoint (`A/endpoints/maintenance.py:182`) or the scheduler | all projects that are not archived (`A/maintenance/operations.py:83-96`), and their organization (`:52-55`) | depends on the operation: 15 operations (`A/maintenance/registry.py:86-288`) | global; the organization of each project through `OWNED_BY` and `BELONGS_TO`; projects with no organization are skipped | 2 s idle poll; a Valkey pending set; lock 12 h, pending 24 h, results 7 d (`A/maintenance/state.py:36-43`) | plugins; Iggy `maintenance_log` (`A/maintenance/log.py:109`) | no delivery guarantee: an item that a stopped pod took is lost, and the run shows `abandoned` after the lock expires (`A/maintenance/state.py:8-10`); a rate limit or a shutdown puts an item back (`:234`) |
| 11 | score worker and daily tick (`A/scoring/queue.py`) | L | consumer group (`A/scoring/queue.py:156`) | `db.match(Project)` (`A/scoring/queue.py:301`); `compute_score` (`C/scoring/engine.py`); all projects (`A/scoring/queue.py:218-224`); `DEPENDS_ON` (`:254`) | Iggy `score_history` first, then `SET p.score` (`C/scoring/history.py:30-60`) | global today; relational: the organization of each project | stream `imbi:score-recompute`, 2 s block, 5 s debounce, 60 s reclaim, dead-letter after 5 deliveries (`A/scoring/queue.py:42-49`); daily tick at 06:00 UTC, polled each 3600 s, once for each date across pods (`:50-52,459-499`) | Iggy | the tick does not run twice for a date; a recompute is idempotent |
| 12 | `imbi-assistant serve` | S | `graph.graph_lifespan` (`apps/assistant/.../app.py:81`); a second graph connection reads `MCPServer` (`app.py:50-71`); loads the OpenAPI tools (`mcp.py:78-99`) | `Conversation`, `Message` (`apps/assistant/.../age_ops.py:222-242`), `MCPServer`; all other data through the API | `CREATE Conversation` and `HAS_CONVERSATION` (`age_ops.py:37-86`); `add_message` (`:154-207`) | the user email today (`apps/assistant/.../endpoints.py:69`); `MCPServer` is global. Relational: conversations under the organization path (D17, WP1.10) with `owner_only`; `mcp_servers` is an organization table, and startup has no organization | none | Anthropic (`endpoints.py:223,657`); the API with the user token (`mcp.py:163-165`); external MCP servers (`external_mcp.py:49-104`) | streams are lost; the user message is written before the stream (`endpoints.py:788`); `add_message` is not idempotent |
| 13 | `imbi-gateway serve` | R | `graph.graph_lifespan` (`apps/gateway/.../app.py:38`); ClickHouse; Iggy (`lifespans.py:15-32`); loads the plugins for the name check only | `Webhook`, its organization, `Integration`, `WebhookRule` (`apps/gateway/.../notifications.py:209-244`); the project through `EXISTS_IN` (`:548-558`) | none in the graph; writes go through the API with `IMBI_GATEWAY_API_TOKEN` (`apps/gateway/.../actions.py:109-128`) | the webhook id gives the organization (`notifications.py:199,211`); relational: `webhook_organization_id(text)` | none | the API; Iggy `events` (`notifications.py:1189,1229`); the plugin actions (GitHub, SonarQube) | stateless, no deduplication in the gateway; the API deduplicates (release create, `external_run_id`) |
| 14 | `imbi-scheduler serve` | O (`apps/scheduler/.../store/`) | ClickHouse; Iggy; `graph.graph_lifespan` for the auth of the routes only (`apps/scheduler/.../app.py:16-32`); `store.store_lifespan` creates the `scheduler` schema with an advisory lock (`store/initializer.py:30-166`) | the graph only for auth (`endpoints/dependencies.py:43-69`); its own tables (`store/tasks.py:295-322`, `SKIP LOCKED`) | the graph only `SET last_used` on API-key auth (`C/auth/permissions.py:475-500`); its own tables (`store/tasks.py:108-131`) | `tasks.organization` (`models.py:147,290`), which becomes `/organizations/<slug>` (`render.py:146-168`) | the engine task (`lifespans.py:67`), ticks up to 30 s, `LISTEN`, advisory-lock leases, at most 20 runs | the API (`/auth/token`, `identity.py:122-137`; `executor.py:268`); gateway posts (`render.py:178-196`); Iggy `scheduler_runs` (`runs.py:237`) | resumes from `next_run_at`, with 300 s misfire grace |
| 15 | `imbi-slackbot serve` | M (`apps/slackbot/.../identity.py`) | `graph.graph_lifespan` (`apps/slackbot/.../app.py:69`); Slack Socket Mode (`slack_handler.py:275-299`) | `MATCH (u:User {email})` (`identity.py:33-36,89-106`), cached for 900 s; all other data through the API | none | the user of a signed JWT (`identity.py:132-154`) | Socket Mode; 15 s drain at shutdown | Slack; Anthropic; the API | stateless; events that arrive while it is down are lost |
| 16 | `imbi-mcp` | S | no database; stops if it cannot read `/openapi.json` (`apps/mcp/.../server.py:125-129`) | the API over HTTP | the API over HTTP | the token of the caller | none (60 s permission cache) | the API | stateless |
| 17 | `imbi-api setup` (`A/entrypoint.py:262-379`) | K (organization), M (seeds) | graph and ClickHouse connections, no `initialize()` | `Organization`, `User` | `MERGE Organization` (`A/auth/seed.py:1031`); permissions and roles; `MERGE` of the admin user and its `MEMBER_OF` (`A/entrypoint.py:437-456`); the service accounts; ClickHouse DDL | the organization typed at the prompt | none | ClickHouse DDL | a second run with the same email resets the admin password |
| 18 | `imbi-api setup-postgres` (`A/entrypoint.py:76`) | V | `G/initializer.py:16-47` (no lock) | the catalog | AGE DDL, the embeddings table and its HNSW index | global | none | none | idempotent and additive; D10 replaces it with `pglifecycle deploy` |
| 19 | `imbi-api setup-permissions` (`A/auth/seed.py:1053`) | M | graph connection | `Permission`, `Role` | `DETACH DELETE` of 4 retired permissions (`:866`); `MERGE` of the permissions (`:893`), 6 roles (`:955`), and `GRANTS` (`:974`) | global | none | none | idempotent; a grant is never removed |
| 20 | `imbi-api setup-service-accounts` (`A/auth/internal_services.py:108`) | K | runs at container start (`container/entrypoint.sh:292`) | the only `Organization` (`A/entrypoint.py:180-205`) | the service accounts (`:166`), `MEMBER_OF` (`:199-212`), credentials (`:280-294,486-493`) | the `--organization` option, or the only organization | none | none (prints the new secrets) | idempotent; a credential is never rotated, but a different id from the environment makes an extra credential |
| 21 | `imbi-api setup-clickhouse` (`A/entrypoint.py:25-53`) | none (no graph) | ClickHouse only | none | ClickHouse DDL | not applicable | none | ClickHouse | idempotent |
| 22 | `python -m imbi.api.backfill_embeddings` (`A/backfill_embeddings.py:134`) | U | graph connection | `db.match` for each embedded type | `public.embeddings` upsert (`G/client.py:731-760`) | all organizations, 4 at a time | none | none | resumable and idempotent; the same work as the `search-reindex` operation |
| 23 | `imbi-common` CLI (`etl audit`, the ETL load, `etl reconcile`) | D (ETL, reconcile), E (audit) | new in this migration; `libraries/common/pyproject.toml` has no console script today | the graph with plain SQL (audit, ETL); the relational tables (reconcile) | the relational tables (ETL) | `imbi_maintenance` (BYPASSRLS), never the application login (D16) | none | none | the ETL is one TRUNCATE and INSERT in the freeze (D20); a failed load runs again from the start |

## Table 2: covered by

Each cell names a test (module and test case) or a rehearsal check, or
says why the cell does not apply. The owner letter is in each cell
until the owner fills it.

| # | Process | Startup | Read | Write | RLS context | Background | Outbound | Restart |
|---|---|---|---|---|---|---|---|---|
| 1 | `imbi-api serve` | V: | replay `record` and `replay` (every `GET` route) | replay `scenarios` | each owner: the isolation matrix (recipe step 5) | each owner: | each owner: | V: |
| 2 | blueprint models | L: | L: | not applicable (no write) | L: | not applicable | not applicable | L: |
| 3 | plugin load | T: | T: | T: | T: | not applicable | not applicable | T: |
| 4 | identity refresh sweeper | M: | M: | M: | M: | M: | M: | M: |
| 5 | document read sweeper | Q: | not applicable (no graph) | not applicable (no graph) | Q: | Q: | Q: | Q: |
| 6 | commit-sync worker | N: | N: | N: | N: | N: | N: | N: |
| 7 | pr-sync worker | N: | N: | N: | N: | N: | N: | N: |
| 8 | deployment-sync worker | O: | O: | O: | O: | O: | O: | O: |
| 9 | release-promote worker | N: | N: | N: | N: | N: | N: | N: |
| 10 | maintenance worker | U: | U: | U: | U: | U: | U: | U: |
| 11 | score worker and tick | L: | L: | L: | L: | L: | L: | L: |
| 12 | `imbi-assistant` | S: | S: | S: | S: | not applicable | S: | S: |
| 13 | `imbi-gateway` | R: | R: | not applicable (the API writes) | R: | not applicable | R: | R: |
| 14 | `imbi-scheduler` | O: | O: | O: | O: | O: | O: | O: |
| 15 | `imbi-slackbot` | M: | M: | not applicable (the API writes) | M: | M: | M: | M: |
| 16 | `imbi-mcp` | not applicable (no database) | replay (the API) | replay (the API) | not applicable (the API does it) | not applicable | not applicable | not applicable |
| 17 | `imbi-api setup` | K, M: | K, M: | K, M: | K, M: | not applicable | not applicable | K, M: |
| 18 | `imbi-api setup-postgres` | V: | not applicable | V: | not applicable | not applicable | not applicable | V: |
| 19 | `imbi-api setup-permissions` | M: | M: | M: | M: | not applicable | not applicable | M: |
| 20 | `imbi-api setup-service-accounts` | K: | K: | K: | K: | not applicable | not applicable | K: |
| 21 | `imbi-api setup-clickhouse` | not applicable (no PostgreSQL) | not applicable | not applicable | not applicable | not applicable | not applicable | not applicable |
| 22 | `backfill_embeddings` | U: | U: | U: | U: | not applicable | not applicable | U: |
| 23 | `imbi-common` ETL CLI | D, E: | D, E: | D: | D: | not applicable | not applicable | D: |

## Open points for the owners

1. **Rows 2 and 12:** `blueprints` and `mcp_servers` are organization
   tables (D17; `schemata/README.md`, Open question 1), but the API
   startup (blueprint models) and the assistant startup (external MCP
   connections) have no organization. The owners (L, S) must say which
   RLS context these reads use: a loop over the organizations, or a
   SECURITY DEFINER lookup. The README lists no such lookup today.
2. **Rows 10 and 11:** the maintenance operations and the daily score
   tick run over all projects. They need one organization context for
   each organization, not one context for the whole run.
3. **Rows 6 to 9:** the stream entries carry `org_slug`. The worker must
   set the organization context from it before its first query.
4. **Row 3:** a plugin schema failure does not stop startup: the
   lifecycle raises again (`A/plugins/lifecycle.py:32-36`), but
   `_on_graph_startup` only logs (`A/lifespans.py:42-45`). With D8 the
   manifest labels become `plugin_entity_keys` rows; T decides whether
   a failure stops startup.
5. **Rows 1 and 12 to 15:** `graph.initialize()` runs at each start of
   the api, assistant, gateway, scheduler, and slackbot, with no lock
   (`G/initializer.py:16-47`). V removes it (WP4.3); until then, two
   pods that start at the same time can both try to create a vlabel
   (inference, not seen).
