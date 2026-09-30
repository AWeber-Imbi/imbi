# AGE cutover runbook

Status: draft for review. This runbook moves a production Imbi database
from the Apache AGE graph to the relational schema in `schemata/`. It is
WP0.8 of the implementation plan
(`meta:docs/age-to-relational-implementation-plan.md`), with the changes
of decisions D25, D27, and D28 of the execution plan
(`meta:docs/age-to-relational-execution-plan.md`).

The SQL of the runbook is in `schemata/cutover/`. The moon task
`root:cutover-check` runs steps 4, 5, and 6, the probe of step 9, and
the rollback on an AGE-era fixture (see "Tests of this runbook"). The rehearsal (WP3.2) runs the full runbook on a
production copy, and makes it fail after each of steps 5 to 12.

## Rules

1. Do the steps in order. Do not start a step before the check of the
   step before it passes.
2. A failed check stops the runbook. Use the decision tree below. Do
   not repair and continue unless the step says so.
3. Before step 13, every failure has a rollback. After step 13, there is
   no rollback. Only forward fixes.
4. Write the time and the result of each check in the cutover log (a
   copy of the table in "Cutover log"). Keep every output file.
5. Nobody writes to production outside these steps.

## Roles

| Role | Who | Does |
|---|---|---|
| Operator | Gavin | Runs every command that changes production: `kubectl`, `helm`, `psql`, the ETL. Makes the go and no-go decisions. |
| Checker | A second person, or an agent session with read-only access | Reads each output and confirms each check. Does not change production. |
| Communicator | The operator, or a person that the operator names | Sends the announcement (step 1) and the end notice (step 13 or the rollback). |

## Build record

The rehearsal and the cutover use the same builds. Record each value at
the rehearsal. At the cutover, the operator compares each value before
step 1. A different value stops the cutover.

| Item | Value | How to get it |
|---|---|---|
| pglifecycle commit | `4f6729cda43b1d8facdeed304e6adfeb4991d18a` (pinned by D27 in `schemata/scripts/install-pglifecycle.sh` and `schemata/README.md`) | `pglifecycle --version` does not show it; read the install script |
| pglifecycle build | `schemata/scripts/install-pglifecycle.sh` (`cargo install --locked --git ... --rev <commit>`). Keep the binary file of the rehearsal and use that file at the cutover. The script gives the same binary each time on one platform, but another build command gives another binary (a `cargo build --release` of the same commit had a different SHA-256 on 2026-09-30) | the script prints the path |
| pglifecycle binary SHA-256 | Linux x86_64: `10b8f2d2ff0381c9378653f4867b30908c11c51c2f124ab9e2e1fc50fdf58561` (the CI Schema job). macOS arm64: `e2ec81979d7e30a2df6c6e6c875988e794dc327a08a4cca67f642e3a44cb2f0e` (the build that `root:cutover-check` used on 2026-09-30). Record the value of the rehearsal workstation; the cutover uses the same file | `shasum -a 256 <binary>`; `root:cutover-check` prints it |
| New release image | the digest of the integration branch build (`ghcr.io/aweber-imbi/imbi@sha256:...`) | the release workflow output |
| Previous release image | the digest of the AGE-era image that production runs before step 1 | `kubectl get deploy -o jsonpath='{..image}'`, then the digest from the registry |
| Monorepo commit | the commit of the new release image; the operator runs every `schemata/` file and CLI from a checkout of this commit | `git rev-parse HEAD` |
| Rehearsal deploy plan | the `cutover.sql` of the last rehearsal (step 6 compares with it) | the rehearsal record |

## Settings

Set these in the operator shell before step 1. The values are
deployment-specific; this runbook does not name them.

```bash
export KCTX=<kubectl context of production>
export NS=<namespace of the Imbi releases>
export AGE_LOGIN=<the login role in the AGE-era POSTGRES_URL>
export PGHOST=127.0.0.1 PGPORT=<local port of the port-forward>
export PGUSER=<operator role: a superuser, not AGE_LOGIN>
export PGDATABASE=<the Imbi database>
export PGLIFECYCLE=<path to the pinned pglifecycle binary>
export CUTOVER=<an empty directory for the outputs of this cutover>
export TENANT_SLUG=<slug of the tenant that the ETL creates>
export TENANT_NAME=<name of that tenant>
```

The operator reaches PostgreSQL through
`kubectl --context "$KCTX" -n "$NS" port-forward svc/<primary service> "$PGPORT":5432`
in a second shell.

## The Deployments

The chart `helm/imbi/` renders one `Deployment` for each Helm release,
from `templates/deployment.yaml`. `service.mode` selects the process:

| `service.mode` | Process | AGE-era image runs `graph.initialize()` |
|---|---|---|
| `all` | every process below in one pod, behind the bundled Caddy; the entrypoint also runs `imbi-api setup-service-accounts` (a write) at each start | yes |
| `api` | `imbi-api serve`, with its background workers in the same process: score recompute, commit sync, pull request sync, deployment sync, release promote, maintenance operations, the identity refresh sweeper, and the document read sweeper | yes |
| `assistant` | `imbi-assistant serve` | yes |
| `gateway` | `imbi-gateway serve` | yes |
| `mcp` | `imbi-mcp serve`; it calls the API | no |
| `scheduler` | `imbi-scheduler serve`; it also writes the schema `scheduler` | yes |
| `slackbot` | `imbi-slackbot serve` | yes |
| `ui` | Caddy: the UI files, and a reverse proxy to the other releases | no |

Every mode writes production data, directly or through the API, except
`ui`. The freeze stops all of them, `ui` too, because the maintenance
page must come from a server that is not Imbi.

`templates/deployment-iggy-connect.yaml` renders a second Deployment,
`<release>-imbi-connect`, when `iggyConnect.enabled` is true. It drains
the Iggy streams into ClickHouse and does not connect to PostgreSQL. It
can stay up. It reads its configuration from imbi-api only when it
starts, so if it restarts while the API is stopped, it exits; restart it
after step 13.

With the default chart name, all Imbi Deployments have the label
`app.kubernetes.io/name=imbi`. The
connectors runtime has `app.kubernetes.io/name=imbi-connect`, so the
label selector below does not stop it.

`graph.initialize()` creates `public.embeddings` when it is not there.
For this reason no AGE-era process can run from step 2 until the
rollback.

## Decision tree

```
A check fails.
|
+-- Did step 13 action 2 start (the database fence is removed)?
    |
    +-- No:  ROLLBACK (below). The relational tables stay. A new attempt
    |        starts again at step 3, after the cause is fixed.
    |
    +-- Yes: NO ROLLBACK. FORWARD FIX (below). The AGE-era image cannot
             see the writes since step 13.
```

A failure in steps 1 to 4 needs no `rollback.sql`: the database has no
change yet. Stop, then do rollback steps 3 to 5 (step 3 only if step 4
ran `freeze.sql`).

## Before the cutover day

1. The integration branch is merged into `main`, and the release image
   exists. Record its digest.
2. The last rehearsal passed (execution plan section 7), with the same
   builds. Its record is in `docs/architecture/age-migration-rehearsal-<date>.md`.
3. The pre-migration audit (WP1.9) on production shows zero for each
   blocking rule (WP3.0 is done).
4. The relational roles exist in production:
   `schemata/scripts/create-roles.sql`, with the passwords from the
   secret store. The secret of the new release has the `imbi_app` and
   `imbi_admin` URLs. The operator has the `imbi_maintenance` URL.
5. `AGE_LOGIN` is not a superuser, is not the operator role, has no
   login role as a member, and is not a role of `schemata/README.md`
   "Roles". If production uses one role for the app and the operator,
   create a separate operator role now. `freeze.sql` checks this again
   in step 4.
6. Nothing starts the apps again by itself during the freeze: pause any
   GitOps sync or automated `helm upgrade` for the Imbi releases, and
   find each autoscaler, Job, and CronJob that uses the Imbi image or
   the database credentials (step 2 lists them).
7. A maintenance page is ready that no Imbi process serves (see step 2).
8. Nothing outside Kubernetes holds the AGE-era database credentials, or
   the operator has a list of those clients and stops them in step 2.
   `freeze.sql` stops the runbook in step 4 when any client that is not
   a superuser is still connected.

## Steps

Each step has a role, the action, and a check. The rehearsal record
gives the measured duration of each step; this runbook gives no
estimate.

### 1. Announcement

- Role: communicator.
- Action: tell the users the start time, that Imbi shows a maintenance
  page for the whole window, that webhook deliveries from GitHub and
  Slack events in the window are delivered again or synchronized after
  step 13, and that API automation (for example `imbi-automations`)
  must not run.
- Check: the operator confirms the builds in "Build record".

### 2. Write freeze: stop every app, show the maintenance page

- Role: operator.
- Action:

  ```bash
  # Every workload in the namespace, not only the Imbi Deployments.
  kubectl --context "$KCTX" -n "$NS" get \
    deploy,statefulset,daemonset,job,cronjob,hpa -o wide \
    | tee "$CUTOVER/02-before.txt"
  # Switch the Ingress (or the load balancer) to the maintenance page.
  kubectl --context "$KCTX" -n "$NS" scale deploy \
    -l app.kubernetes.io/name=imbi --replicas=0
  # Suspend each CronJob that uses the Imbi image or the database, and
  # stop each other client of the list of "Before the cutover day".
  ```

  The chart has no Job, CronJob, or autoscaler, but a deployment can add
  them. An autoscaler on an Imbi Deployment must be removed or set to
  zero, or it scales the Deployment up again.

  The maintenance page is a static page that a separate server gives
  for every path, with status 503 and a `Retry-After` header. A 503 on
  `/api/*` tells automation to try again later. Recommended: a small
  web server Deployment and Service in the namespace, and a change of
  the Ingress backend to it. The Imbi `ui` mode is not acceptable: it is
  an Imbi process of the AGE-era image.

- Check:

  ```bash
  kubectl --context "$KCTX" -n "$NS" get pods \
    -l app.kubernetes.io/name=imbi   # expect: No resources found
  curl -s -o /dev/null -w '%{http_code}\n' https://<imbi host>/api/status
  # expect: 503 from the maintenance page
  ```

- Why: D28. The AGE-era image has no read-only mode, and a stop is
  simpler. A sign-in and an API key "last used" update are writes too,
  so the API cannot stay up.

### 3. Final audit

- Role: operator.
- Action: run the audit (WP1.9) on the frozen graph, from the monorepo
  checkout of the release commit:

  ```bash
  uv run --frozen imbi-common etl audit <options of the WP1.9 CLI> \
    > "$CUTOVER/03-audit.json"
  ```

- Check: the exit code is 0, and each blocking count in the JSON is
  zero. Keep the JSON.

### 4. Guard the database

- Role: operator.
- Action:
  1. Check again that every Imbi Deployment has zero pods (step 2
     check).
  2. Block the AGE-era login and end its sessions. Do not use `-1`:

     ```bash
     psql -v ON_ERROR_STOP=1 -v age_login="$AGE_LOGIN" \
       -f schemata/cutover/freeze.sql | tee "$CUTOVER/04-freeze.txt"
     ```

     The script stops unless `AGE_LOGIN` is a separate role (not the
     operator, not a superuser, not an `imbi_*` role, and no login role
     is a member of it, directly or through another role). Then it runs
     `ALTER ROLE ... NOLOGIN`, ends the sessions of that role, and checks
     that none remains. `NOLOGIN` does not end a session that is already
     open. Last, it stops when any other client that is not a superuser
     is connected to the database: every app is stopped, so such a
     client is a writer that the inventory missed. Find it, stop it, and
     run the script again.
  3. Take a physical backup of the frozen database (the backup method of
     the cluster, for example a CloudNativePG `Backup`). This backup is
     the last resort of the forward-fix branch. It is not the rollback.
     A restore of it has `AGE_LOGIN` as NOLOGIN: after a restore, run
     rollback step 3.
- Check: `freeze.sql` prints `freeze: <login> is NOLOGIN and has no
  session`, and the backup has completed.

### 5. Pre-deploy

- Role: operator.
- Action:

  ```bash
  psql -1 -v ON_ERROR_STOP=1 -f schemata/cutover/pre-deploy.sql
  ```

  In one transaction, the script checks that the database is in the
  AGE-era state, records the OID and row count of `public.embeddings`
  and the schema of the `vector` extension in `legacy.cutover_state`,
  and moves `public.embedding_distance(agtype, ...)` and
  `public.embeddings` into the schema `legacy`. The indexes move with
  the table. The function moves, not drops, so the rollback can put it
  back as it was. It has `lock_timeout = 10s`: with every app stopped,
  a lock wait means that a client is still connected.
- Check:

  ```bash
  psql -At -c "SELECT (SELECT count(*) FROM legacy.embeddings),
                      embeddings_rows, vector_schema
                 FROM legacy.cutover_state"
  # expect: two equal row counts, and ag_catalog (the production dump of
  # 2026-08-17 has vector there)
  ```

### 6. Deploy the schema

- Role: operator (the checker reads the plan).
- Action:
  1. Make the plan. Never use `--allow-drop` here:

     ```bash
     "$PGLIFECYCLE" deploy -o "$CUTOVER/cutover.sql" \
       -N imbi -N ag_catalog -N scheduler -N legacy \
       --exclude-extension age --exclude-extension pg_cron schemata/
     ```

  2. Compare the plan with the plan of the last rehearsal. Only the
     `-- source:` line can differ:

     ```bash
     diff <(grep -v '^-- source:' "$CUTOVER/cutover.sql") \
          <(grep -v '^-- source:' <rehearsal>/cutover.sql)
     ```

  3. Apply the plan and the two checks in one transaction. Deploy at the
     pinned commit sets the owners that the YAML names, so
     `set-owners.sql` changes nothing: it fails the transaction when an
     owner is wrong.

     ```bash
     PGOPTIONS='-c lock_timeout=10s' \
       psql -1 -v ON_ERROR_STOP=1 -f "$CUTOVER/cutover.sql" \
       -f schemata/scripts/set-owners.sql \
       -f schemata/cutover/checks.sql
     ```

- Check:
  - The plan header says `-- destructive statements: none`, and the
    `diff` is empty.
  - `psql` exits 0. `checks.sql` fails the transaction when the tables,
    an owner, a grant (also a grant that default privileges of the
    AGE-era database add), the row-level security, the policy, trigger,
    or foreign key counts, a role attribute, an index that is not valid,
    a constraint that is not validated, the `search_path` of a SECURITY
    DEFINER function, or the place of the `vector` extension is not as
    expected. The deploy itself compares every definition with the
    project; `checks.sql` covers what the deploy does not.
  - A second deploy (`deploy --allow-drop -o "$CUTOVER/second.sql"` with
    the same flags) has only the statements of
    `schemata/tests/second-deploy-allowlist.sql` (README Known problem
    2). Do not apply it.
- Notes:
  - The plan has `ALTER EXTENSION vector SET SCHEMA public`, because
    the graph initializer created the extension in `ag_catalog`.
    `rollback.sql` moves it back.
  - `-N legacy` is necessary until WP4.2. Without it, each deploy
    proposes `DROP SCHEMA legacy`.

### 7. ETL

- Role: operator.
- Action: load the graph into the relational tables (WP1.5), as
  `imbi_maintenance`. The source is the same database: the source
  connection uses the operator role, because `AGE_LOGIN` cannot log in
  since step 4.

  ```bash
  # The passwords come from ~/.pgpass, not from the command line.
  export IMBI_ETL_SOURCE_URL=postgresql://$PGUSER@$PGHOST:$PGPORT/$PGDATABASE
  export IMBI_ETL_TARGET_URL=postgresql://imbi_maintenance@$PGHOST:$PGPORT/$PGDATABASE
  uv run --frozen imbi-common etl run --graph imbi \
    --tenant-slug "$TENANT_SLUG" --tenant-name "$TENANT_NAME" \
    2>&1 | tee "$CUTOVER/07-etl.txt"
  ```

  The options are those of the WP1.5 CLI on 2026-09-30 (agent D's
  draft); the rehearsal confirms them. `TENANT_SLUG` and `TENANT_NAME`
  name the one tenant that the ETL creates (Appendix E, E2); use the
  same values in step 9. Never pass `--allow-pending` here: it lets
  tables without a mapping stay empty. The ETL truncates the tables
  that it loads and inserts in foreign key order, in one transaction.
  It can run again.
- Check: the exit code is 0.

### 8. Embeddings

- Role: operator.
- Action: the WP2.10 mapping copies `legacy.embeddings` into
  `public.embeddings`, with the `organization_id` from the loaded
  tables. It skips the rows of entities that were not loaded and the
  `Component` and `Role` rows (Appendix E, E29 and E32).
- Check: the count of `public.embeddings` equals the count of
  `legacy.embeddings` minus the skipped rows in the ETL output.
- If the copy fails: `search-reindex` rebuilds the index after step 13
  instead. Record this in the log. Search returns fewer results until
  the rebuild ends.

### 9. Reconciliation

- Role: operator; the checker reads the report.
- Action:

  ```bash
  uv run --frozen imbi-common etl reconcile --graph imbi \
    --tenant-slug "$TENANT_SLUG" --tenant-name "$TENANT_NAME" \
    --output "$CUTOVER/09-reconcile.json"
  ```

- Check: the exit code is 0, and the report is clean: each count equals
  the expected count, and the skipped rows equal the expected skips.
- Action, second part: probe row-level security on the loaded data.
  Production has one organization, so step 12 cannot request a real row
  of another organization through the API. The probe tests the policies
  directly, as `imbi_app`, in a transaction that it rolls back:

  ```bash
  psql -v ON_ERROR_STOP=1 \
    -v org_id="$(psql -At -c 'SELECT id FROM public.organizations LIMIT 1')" \
    -f schemata/cutover/rls-probe.sql | tee "$CUTOVER/09-rls-probe.txt"
  ```

- Check: the probe prints `isolation holds`. For each organization
  table, `imbi_app` sees exactly the rows of the organization with its
  setting, no row with the setting of an unknown organization, and no
  row with no setting. An insert for another organization fails.

### 10. Caches and other stores

- Role: operator.
- Action:
  1. Record the Valkey keys by prefix, for the log:
     `valkey-cli --scan --pattern '*' | cut -d: -f1-2 | sort | uniq -c`.
  2. Flush the Valkey database of Imbi (`FLUSHDB`). D30 keeps this
     step at the cutover. If the Valkey server is shared with other
     applications, delete the Imbi keys by prefix instead. The prefixes
     are in "Valkey keys".
  3. ClickHouse, Iggy, and S3 need nothing at the cutover: WP3.4 is
     after the cutover (D30).
- Check: `DBSIZE` returns 0 (or no key with an Imbi prefix remains).

### 11. Record the write counters

- Role: operator.
- Action:

  ```bash
  psql -At -f - > "$CUTOVER/11-counters.txt" <<'SQL'
  SELECT schemaname || '.' || relname,
         n_tup_ins, n_tup_upd, n_tup_del
    FROM pg_stat_user_tables
   WHERE schemaname IN ('public', 'legacy', 'scheduler', 'imbi')
   ORDER BY 1;
  SQL
  ```

- Check: the file has a line for each table of `public` (74).

### 12. Start the new release read-only, and validate

- Role: operator; the checker does the reads.
- Action:
  1. Make the database refuse writes from the app logins. This is the
     database fence; `IMBI_READ_ONLY` is the application fence:

     ```bash
     psql -v ON_ERROR_STOP=1 \
       -c "ALTER ROLE imbi_app SET default_transaction_read_only = on" \
       -c "ALTER ROLE imbi_admin SET default_transaction_read_only = on"
     ```

     The setting applies to each new session of these logins. A write
     then fails with SQLSTATE 25006 (`read_only_sql_transaction`), and
     the log shows it.
  2. Deploy the new release image to the `api` and `ui` releases only,
     with `IMBI_READ_ONLY=true`. The `assistant`, `gateway`, `mcp`,
     `scheduler`, and `slackbot` releases stay at zero replicas. If
     production runs `service.mode: all`, do not start it: deploy a
     separate `api` release and a `ui` release for this step, because
     `all` starts every worker and runs `setup-service-accounts`.
  3. The maintenance page stays for the users. The checker reaches the
     new release directly (a port-forward to the `ui` or `api`
     Service).
  4. Validate with reads only:
     - the baseline routes (WP1.8, Appendix C of the implementation
       plan), each 200;
     - a sample of the replay routes (execution plan section 6), with
       the same bodies as the AGE-era record, except the expected
       differences;
     - a label-filtered search that returns rows;
     - a request for a real project through an organization slug that
       does not exist, which must return 404 (the row-level security
       itself is proved by the probe of step 9);
     - one write, which must return 503;
     - the logs of the new pods: no error that names the graph (`agtype`,
       `ag_catalog`, `cypher`), no SQLSTATE 25006 (a write that the
       application fence missed), and no status 500.
  5. Wait more than 10 seconds after the last request, so that the
     backends flush their statistics, then record the counters again,
     into `$CUTOVER/12-counters.txt`, with the query of step 11 (a new
     `psql` session reads a new statistics snapshot).
- Check: every read passes, the write returns 503, the logs have no
  SQLSTATE 25006, and
  `diff "$CUTOVER/11-counters.txt" "$CUTOVER/12-counters.txt"` is
  empty. The counters are the second signal after the database fence:
  a changed counter or a 25006 error means that a process tried to
  write. That stops the cutover.
- Why: D25. The point of no return is the first write to the relational
  tables, not the start of the new image. This step proves that the new
  image serves the data before anything can write.

### 13. Turn writes on: the point of no return

- Role: operator; go or no-go decision by the operator.
- Action, in this order:
  1. Decide go or no-go. Write the decision, the time, and the name of
     the operator in the log. The point of no return is the next
     action: a writable pod can write while it starts, before it is
     ready.
  2. Remove the database fence:

     ```bash
     psql -v ON_ERROR_STOP=1 \
       -c "ALTER ROLE imbi_app RESET default_transaction_read_only" \
       -c "ALTER ROLE imbi_admin RESET default_transaction_read_only"
     ```

  3. Set `IMBI_READ_ONLY=false` on the `api` release and deploy it. The
     new pods open new sessions, which do not have the fence. Wait until
     the `api` pods are ready.
  4. Deploy the new image to `assistant`, `gateway`, `mcp`, `scheduler`,
     and `slackbot`, and go back to the normal layout of production
     (take away the temporary releases of step 12 if you made them).
  5. Switch the Ingress back from the maintenance page to Imbi.
  6. The communicator sends the end notice.
- Check: `GET /api/status` returns 200 through the Ingress, and one
  write through the UI works (for example a change to a tag
  description, then back).

From now on, the decision tree has no rollback.

### 14. Watch

- Role: operator and checker.
- Action and check, for the watch period that the operator sets:
  - the baseline routes and the error rate (logs, Sentry) against the
    values before the cutover;
  - the write counters of `public` increase, and the counters of the
    schema `imbi` do not change;
  - send again the GitHub webhook deliveries that failed in the window
    (the delivery log of each webhook, or the GitHub API), or run
    "Sync Commits & Tags" and "Sync Deployments" for the projects;
  - the scheduler occurrences that the window missed, as the scheduler
    reports them;
  - search returns results (if step 8 failed, run `search-reindex` for
    each organization now).

### 15. Keep AGE readable

- Role: operator.
- Action: keep the graph (schema `imbi`), `legacy.embeddings`, and the
  NOLOGIN `AGE_LOGIN` for 14 days (proposed). Then WP4.2 drops AGE,
  `legacy`, and `pg_cron`, and WP4.2 removes `-N legacy` from the deploy
  flags.
- Check: the write counters of the schema `imbi` stay the same as in
  step 11.

## Rollback (before step 13 only)

Use it for a failed check in any step from 5 to 12, or when the operator
says no-go at step 13.

1. Stop every app, as in step 2: every Deployment with
   `app.kubernetes.io/name=imbi` has zero pods. The maintenance page
   stays.
2. Put the legacy table back:

   ```bash
   psql -1 -v ON_ERROR_STOP=1 -f schemata/cutover/rollback.sql \
     | tee "$CUTOVER/rollback.txt"
   ```

   The script can run after a failure at any step from 5 on, and it can
   run again. It stops unless `legacy.embeddings` is the table that step
   5 moved (its OID). It drops the new `public.embeddings` only when
   `legacy.embeddings` exists, moves the legacy table back with its
   rows, indexes, owner, and grants, moves `embedding_distance` back,
   moves the `vector` extension back to the schema that step 5
   recorded, and drops the schema `legacy`. The relational tables stay.
3. Let the AGE-era login connect again, and remove the database fence of
   step 12 if it was set:

   ```bash
   psql -v ON_ERROR_STOP=1 -c "ALTER ROLE \"$AGE_LOGIN\" LOGIN" \
     -c "ALTER ROLE imbi_app RESET default_transaction_read_only" \
     -c "ALTER ROLE imbi_admin RESET default_transaction_read_only"
   ```

4. Flush the Imbi Valkey keys again (step 10): the new image can have
   written cache values in step 12.
5. Deploy the previous release image (the AGE-era digest in "Build
   record") to every release, with its old values. Switch the Ingress
   back from the maintenance page, and send the end notice.

Check after the rollback:

- `public.embeddings` has the row count of step 5, and its three
  indexes (`embeddings_pkey`, `embeddings_node_idx`,
  `embeddings_text_hnsw_idx`);
- the AGE-era apps start, `GET /api/status` returns 200, a project page
  opens, and search returns results;
- one write through the UI works.

A new attempt starts again at step 3, after the cause is fixed. Step 6 then creates only the new embeddings table (and moves
`vector` again), and the ETL truncates the other tables.

## Forward fix (after step 13)

After the first write, the relational tables have data that the graph
does not have. The previous image cannot serve it, and there is no
reverse ETL (decision O1). So:

1. Keep the new release running, if it serves most requests. A broken
   route is better than a lost write.
2. If the damage grows (wrong data is written), set `IMBI_READ_ONLY=true`
   on the `api` release and stop the workers. This keeps the data as
   it is while you fix it.
3. Fix the code on a branch from the release commit, build the image,
   and deploy it. Fix the data through the API, or with SQL as
   `imbi_maintenance` that the operator approves and the log records.
4. Last resort, only by the operator's decision: restore the physical
   backup of step 4 and do the rollback steps 3 to 5. The restored
   database is in the state of the end of step 4, so `rollback.sql` has
   nothing to do, and `AGE_LOGIN` is NOLOGIN until rollback step 3. This
   loses every write since step 13. Record who decided and why. The
   rehearsal does not test this restore unless the operator adds it.

## Valkey keys

The prefixes that the code of 2026-09-30 writes. `FLUSHDB` in step 10
removes all of them.

| Prefix | Use |
|---|---|
| `imbi:commit-sync`, `imbi:pr-sync`, `imbi:deployment-sync`, `imbi:release-promote`, `imbi:score-recompute` | work streams, debounce keys, and pause keys of the API workers |
| `imbi:maintenance` | the state of maintenance operations |
| `imbi:document:editing`, `imbi:document:readmeta`, `imbi:document:read-sweeper` | document presence, read sessions, and the sweeper lock |
| `imbi:oauth:state-nonce:`, `oauth:authcode:`, `identity:state:nonce:` | sign-in and identity flow state (short time to live) |
| `imbi:plugins:reload` | a pub/sub channel (no stored key) |
| `events` | the gateway event stream |
| `scheduler_runs` | the scheduler run stream |
| the CloudWatch resolve cache of `plugins/aws`, and the installation tokens of `plugins/github` | plugin caches |

## Cutover log

Copy this table for each attempt.

| Step | Start | End | Check result | Output file | Checker |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | `02-before.txt` | |
| 3 | | | | `03-audit.json` | |
| 4 | | | | `04-freeze.txt` | |
| 5 | | | | | |
| 6 | | | | `cutover.sql`, `second.sql` | |
| 7 | | | | `07-etl.txt` | |
| 8 | | | | | |
| 9 | | | | `09-reconcile.json` | |
| 10 | | | | | |
| 11 | | | | `11-counters.txt` | |
| 12 | | | | `12-counters.txt` | |
| 13 | | | | | |
| 14 | | | | | |

## Tests of this runbook

`moon run root:cutover-check` runs `schemata/cutover/cutover-check.sh`
on a new database:

1. It builds the AGE-era fixture (`schemata/cutover/fixture/age-era.sql`):
   the DDL of the production dump of 2026-08-17, with `vector` in
   `ag_catalog`, the legacy `public.embeddings` with rows and its three
   indexes, `public.embedding_distance`, a small graph, and the schema
   `scheduler`. It adds `pg_cron` when the database is the one that
   `cron.database_name` names.
2. `freeze.sql` refuses the operator role, `imbi_app`, and a role with a
   direct or an indirect login member. It stops while another client is
   connected. It blocks a stand-in AGE-era login, ends its open session,
   and passes again on a second run. `ALTER ROLE ... LOGIN` lets the
   login connect again.
3. `rollback.sql` changes nothing on the AGE-era database, and undoes a
   `pre-deploy.sql` that no deploy followed (a failure in step 6).
4. Steps 5 and 6: the plan has no destructive statement, and
   `--allow-drop` adds none. The plan, `set-owners.sql`, and
   `checks.sql` apply in one transaction, and a second deploy equals the
   allowlist.
5. `checks.sql` fails on each defect of a list of 15: for example a grant
   to `PUBLIC`, a wrong owner, a table without FORCE, a catalog grant, a
   function grant, `vector` in the wrong schema, a role attribute, a
   login role in an owner role, an extra table, a missing legacy table,
   a SECURITY DEFINER function without its `search_path`, and a
   constraint that is not validated.
6. `rls-probe.sql` passes on two organizations, and fails when a policy
   shows the rows of another organization.
7. `rollback.sql`, twice: `public.embeddings` has its rows, indexes, and
   owner again, `embedding_distance` and `vector` are back, the AGE-era
   search query uses the HNSW index, and the relational tables stay.
   `pre-deploy.sql` refuses to run twice without a rollback.
8. Steps 5 and 6 again, with the same checks.

The graph and the schema `scheduler` stay the same in every step.

What the check does not cover: the ETL, the reconciliation, the apps,
the database fence of step 12, and the data of production. The
rehearsal covers them. It also measures the duration of each step.

## Review

Rhona reviewed this runbook on 2026-09-30 (session
age-cutover-runbook-2026-09-30), from a summary. Adopted:

- `embedding_distance` moves to `legacy` and back, not a drop.
- A database fence for step 12 (`default_transaction_read_only` on the
  app logins), with the write counters as the second signal.
- The point of no return is before the first writable pod starts, not
  the Ingress switch.
- `freeze.sql` finds indirect members, and stops while any client that
  is not a superuser is connected. Step 2 lists every workload kind.
- `rollback.sql` checks the OID of the legacy table and reports a
  changed row count.
- `lock_timeout` on the DDL steps; `checks.sql` checks index validity,
  constraint validation, and the SECURITY DEFINER `search_path`.
- A row-level security probe on the loaded data (step 9), because
  production has one organization.
- The backup of step 4 is physical, and its restore needs rollback
  step 3.

Not adopted, with the reason:

- A separate SELECT-only role for step 12. The `organization_isolation`
  policy of `integrations` names `imbi_app`, so another role would read
  other rows than the app does. The role setting on `imbi_app` is a
  database fence with no schema change.
- The HNSW churn of the second deploy as a blocker. It is README Known
  problem 2, a pglifecycle defect, and the allowlist is exact. Nobody
  applies the second deploy in production.
- Full schema fingerprints in `checks.sql`. The second deploy compares
  each definition with the project and must equal the allowlist.
  `checks.sql` covers what the deploy does not see: grants from default
  privileges, role attributes, owners, and the state of the legacy
  objects.
- Sequence checks. The schema has no sequences and no identity columns.
- Failure injection at every boundary in CI. The rehearsal makes the
  runbook fail after each of steps 5 to 12 (execution plan section 7).
  `pre-deploy.sql`, the plan, and `rollback.sql` are single
  transactions, so a failure inside one leaves no partial state.
  `freeze.sql` can run again.

## Questions for review

1. `AGE_LOGIN`: which role is the AGE-era login in production, and is
   it separate from the operator role? If it is named `imbi_app` or
   `imbi_admin`, the relational roles cannot be created as written.
2. Production layout: one `all` release, or one release per service?
   Step 12 needs `api` and `ui` releases without the workers.
3. Valkey: is the Valkey database only for Imbi (`FLUSHDB` in step 10)?
4. The maintenance page: which server, and does the Ingress belong to
   the chart or to the cluster setup?
5. The restore of the step 4 backup: add it to the rehearsal, or accept
   it as not tested?
6. pglifecycle: the SHA-256 depends on the platform and the build
   command. Keep the binary file of the rehearsal workstation for the
   cutover, or build a container image with pglifecycle once and pin its
   digest?
7. The 14 days of step 15 are a proposal.
