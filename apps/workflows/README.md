# Imbi Workflows

The workflow engine (ADR 0021). It claims queued and running workflow runs
from the `workflow_runtime` Postgres schema, runs one step per claim, records
the result, and releases the run. imbi-api owns the schema, starts runs, and
cancels them; the engine has no public API, only `/status`.

Deploy, rollback, and email steps call imbi-api as the `imbi-workflows`
service account. The bounds of ADR 0017 apply to deployments: the account
needs `integration:act-as-service`, membership in the workflow's
organization, and a target environment with `allow_autonomous`. imbi-api
sends email, to users and teams of the organization only.

The engine also reconciles trigger bindings. When a workflow activates,
pauses, or is deleted, imbi-api writes the desired bindings to
`workflows.trigger_bindings` and notifies. The engine then makes the
scheduler task of each schedule trigger (as the `imbi-workflows` account)
and the `gateway-actions#start_workflow` rule of each webhook trigger, and
records each binding as `synced` or `failed`. It also does this on a
schedule, so a failed call is tried again.

## Settings

| Variable | Purpose | Default |
|---|---|---|
| `IMBI_INTERNAL_API_URL` | In-cluster origin of imbi-api | `http://localhost:8000` |
| `IMBI_API_URL` | imbi-api's public URL, whose path is its route prefix | |
| `IMBI_WORKFLOWS_SA_CLIENT_ID` | Client id of the `imbi-workflows` service account | |
| `IMBI_WORKFLOWS_SA_CLIENT_SECRET` | Client secret of that account | |
| `IMBI_WORKFLOWS_WORKERS` | Runs one process works on at the same time | `10` |
| `IMBI_WORKFLOWS_POLL_INTERVAL` | Upper bound in seconds on the sleep between polls | `10` |
| `IMBI_WORKFLOWS_SCHEDULER_URL` | imbi-scheduler's task API, with its route prefix | `http://localhost:8005/api` |
| `IMBI_WORKFLOWS_RECONCILE_INTERVAL` | Seconds between passes of the trigger reconciler | `300` |

Postgres and the graph use the shared settings of `imbi-common`.

## Developer Quickstart

```shell
moon run root:setup
moon run root:services
uv run --env-file .env.test pytest apps/workflows/tests
```
