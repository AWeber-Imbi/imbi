# Graph Workbench Audit

Status: Draft for the maintainer's decision (implementation plan WP0.7,
gate G6), 2026-09-30.

The graph workbench is the admin "Graph Query" page. It sends raw
Cypher to `POST /admin/graph/query` and reads labels and counts from
`GET /admin/graph/schema`. After the move to relational tables (ADR
0020), there is no graph to query. D13 gives two choices: retire the
workbench, or replace it with a read-only SQL console outside the LLM
toolset. This page answers the three WP0.7 questions and gives a
recommendation. The maintainer decides.

## Result of the usage queries

**The production usage counts are not in this document yet.** The
permission system refused the read-only query of production data for
this work package, so the queries were not run. The exact queries are
in "Queries for the maintainer" below. After a person runs them, put the
numbers in the table below and remove this paragraph.

Four clients can call the route: the UI, the MCP server, the assistant,
and the Slack bot.

| Question | Source | Count (last 90 days) |
|---|---|---|
| All calls to `POST /admin/graph/query`, by principal and status | API access log (logz.io), query L1 | not run |
| Calls through the MCP server | MCP access log (logz.io), query L2 | not run |
| Calls by the assistant | `Message.tool_use` in the production graph, query P1 | not run |
| Calls by the Slack bot | API access log by client address, query L3; failed calls also in the Slack bot log | not run |
| Calls from the UI | L1 minus L2, P1, and L3 | not run |
| Rows in ClickHouse `events` or `operations_log` for the route | ClickHouse, query C1 | 0 by construction (see question 1) |

## Question 1: who called `POST /admin/graph/query`

ClickHouse cannot answer this question. `graph_query.py` writes nothing
to ClickHouse. `events` holds project events (webhooks, lifecycle, and
document events), keyed by `project_id`. `operations_log` holds
deployment and other operations entries. Neither table records HTTP
requests (`libraries/common/src/imbi/common/clickhouse/schemata.toml`).
Query C1 confirms this.

These records do have the calls:

1. **The API access log.** `imbi.common.access_log` writes one line for
   each request, in this form:
   `<ip>:<port> - <principal> "POST <prefix>/admin/graph/query HTTP/1.1" <status>`.
   The path has the `/api` prefix or not, as `IMBI_API_URL` sets it at
   startup (`apps/api/src/imbi/api/app.py`). The principal is the local
   part of the JWT subject, or the API key owner, or the key id.
2. **The API application log.** `run_graph_query()` logs
   `Graph query: principal=<name> columns=[...]` at INFO before it runs
   the query, and `Graph query failed: principal=<name> error=...` on a
   database error.
3. **The MCP access log.** `AccessLogContextMiddleware` adds
   `(tool:<name>)` to the line of each MCP tool call.
4. **The Slack bot log.** `apps/slackbot/src/imbi/slackbot/mcp.py` logs
   only a failed tool call: `Tool returned error: <name>: ...` or
   `Tool execution failed: <name>`. A successful call has no line of its
   own.

The MCP server, the assistant, and the Slack bot call the API on the
internal URL with the caller's own bearer token. So the API access log
names the person for all four clients, but it does not name the client.
The client split comes from L2 (MCP), P1 (assistant), and L3 (Slack
bot). The rest are UI calls.

## Question 2: saved queries

There is no server-side store of saved queries. The code has no
`SavedQuery` label, table, or endpoint.

The UI keeps a history in the browser only. `GraphQueryContext.tsx`
stores up to 100 entries (`HISTORY_LIMIT`) in `localStorage`, under the
key `imbi-cypher-history`, as `{query, executedAt}`. Each browser of
each admin has its own history. Nothing sends it to the API. To see a
history, the admin opens the browser developer tools and reads that
key. A retire or a replace does not need to move it, and a Cypher query
does not run on the SQL console.

## Question 3: MCP server, assistant, and Slack bot

All three can invoke the tool today, for an admin.

- The route is a tool in each toolset. Each one builds its tools from
  the API OpenAPI document with `excluded_route_maps()` and
  `exclude_non_ai_tools()` from `imbi.common.mcp`. They exclude only the
  auth, MFA, status, and thumbnail routes, and the operations with
  `x-imbi-ai-tool: false`. `AI_TOOL_EXCLUDED_TAGS` in
  `apps/api/src/imbi/api/openapi.py:65` has only
  `'Project: Configuration'`, not `'Admin: Graph Query'`. The tool name
  is the operation id, `run_graph_query_api_admin_graph_query_post`.
- The MCP server (`apps/mcp/src/imbi/mcp/server.py`) filters
  `tools/list` with `PermissionFilterMiddleware`. The route has
  `x-imbi-permission: ['admin']`, so only an admin sees the tool. The
  test `test_admin_sees_every_tool` in
  `libraries/common/tests/test_mcp.py` pins this.
- The assistant (`apps/assistant/src/imbi/assistant/mcp.py`) and the
  Slack bot (`apps/slackbot/src/imbi/slackbot/mcp.py`) build their
  toolsets without the permission filter. Every user of each gets the
  tool definition, and the API returns 403 for a user who is not an
  admin.
- `POST /admin/graph/query` runs the Cypher with no read-only
  transaction and no statement timeout (`Graph.execute(raw=True)`). An
  admin, or a model that acts for an admin, can write or delete graph
  data through it.

Whether a model ever called it is a usage question: queries L2, P1,
and L3.

## Recommendation

**Retire the workbench** (implementation plan WP3.3, "Retire").

Reasons:

1. The Cypher tool has no target after the cutover. A replacement is a
   new feature, not a port: a new `imbi_readonly` role with
   `default_transaction_read_only`, `statement_timeout`, `lock_timeout`,
   low `work_mem`, `temp_file_limit`, a restricted `search_path`, row
   and byte caps, an audit log, and a new UI.
2. Under row-level security, a SQL console that is useful to an admin
   must see more than one organization. `imbi_app` cannot. The console
   then needs its own login with its own policies, which is a second
   security surface next to the one that ADR 0020 builds.
3. Saved queries are only in browsers, so nothing is lost on the
   server.
4. Today the tool is in three LLM toolsets and can write. D13 requires
   the opposite for a console that stays.
5. Operators can already query production with `psql` through
   `kubectl exec` into the PostgreSQL pod. That path has its access
   control outside Imbi.

Without the counts, this page cannot say that nobody uses the
workbench. The recommendation is to retire it unless the counts show a
need. The steps:

1. A person with production access runs L1, L2, L3, P1, and C1, and
   records the numbers here.
2. The counts name the users. Ask them which queries they run, and
   whether a `psql` session or an API endpoint covers each one.
3. Unless the counts show regular use by people other than the
   platform team, the Wave 3 cleanup retires the workbench (WP3.3).
4. If the counts show that need, keep the retire in the migration, and
   build a SQL console after the cutover as its own work package, with
   a security review. A role with a read-only name is not a security
   boundary: the console needs its own login, read-only transactions,
   short statement and lock timeouts, row and output limits,
   cancellation, a durable audit log, restricted schemas and functions,
   and an explicit rule for access across organizations.

Until the cutover, a small change to `main` removes the risk of point 4:
add `'Admin: Graph Query'` to `AI_TOOL_EXCLUDED_TAGS`. That change is
outside this work package and needs the maintainer's approval.

## Queries for the maintainer

All queries read only. Run each one for the last 90 days
(2026-07-02 to 2026-09-30).

### L1: API access log, by principal (logz.io)

Search the imbi-api logs with this Lucene query. It has no `/api`
prefix, so it matches both forms of the path:

```
"admin/graph/query" AND "POST"
```

Split the result by principal: the third field of the message, after
`<ip>:<port> - `. Count the lines for each principal and each status.
If the logs have the application logger name as a field, this second
search gives the principal as a field value:

```
"Graph query: principal="
```

If logz.io keeps fewer than 90 days, record the window that it keeps.

### L2: MCP tool calls (logz.io)

Search the imbi-mcp logs:

```
"tool:run_graph_query_api_admin_graph_query_post"
```

Count the lines and split them by principal, as in L1.

### L3: Slack bot calls (logz.io)

First, the failed calls, from the imbi-slackbot logs:

```
"run_graph_query_api_admin_graph_query_post" AND ("Tool returned error" OR "Tool execution failed")
```

Then, all calls: split the L1 lines by the client address (the first
field, `<ip>:<port>`). When the Slack bot runs in its own pod, its pod
address marks its calls. When all services run in one container (the
`all` mode), the address is the same for each client, and only the
failed calls are countable.

### P1: assistant tool calls (production PostgreSQL, the AGE graph)

The assistant stores each assistant message with its `tool_use` blocks
as a JSON string property of a `Message` vertex. Run on the production
database as a read-only session:

```sql
BEGIN READ ONLY;
LOAD 'age';
SET LOCAL search_path = ag_catalog, "$user", public;
SELECT count(*) AS messages,
       count(DISTINCT props ->> 'conversation_id') AS conversations
  FROM (SELECT properties::text::jsonb AS props
          FROM imbi."Message") AS m
 WHERE props ->> 'tool_use' LIKE '%run_graph_query%'
   AND props ->> 'created_at' >= '2026-07-02';
ROLLBACK;
```

This query was tested on a scratch AGE database with a fixture of four
messages: it counted the two recent graph-query messages in one
conversation, and skipped the old one and the user message. This count
misses conversations that users deleted: a conversation delete also
deletes its messages.

### C1: ClickHouse confirmation

First find the cluster name:

```sql
SELECT DISTINCT cluster FROM system.clusters;
```

Then run the check with `clickhouse-client --readonly 1`. `cluster()`
reads one replica for each shard, so each row counts once.
(`clusterAllReplicas()` reads every replica of a replicated table, so
it counts each row once for each replica.)

```sql
SELECT 'events' AS source, count() AS rows
  FROM cluster('<cluster>', imbi.events)
 WHERE recorded_at >= now() - INTERVAL 90 DAY
   AND (positionCaseInsensitive(type, 'graph') > 0
        OR positionCaseInsensitive(toString(metadata), 'graph/query') > 0
        OR positionCaseInsensitive(toString(payload), 'graph/query') > 0)
UNION ALL
SELECT 'operations_log', count()
  FROM cluster('<cluster>', imbi.operations_log)
 WHERE occurred_at >= now() - INTERVAL 90 DAY
   AND (positionCaseInsensitive(description, 'graph/query') > 0
        OR positionCaseInsensitive(entry_type, 'graph') > 0);
```

The expected result is 0 for both rows.
