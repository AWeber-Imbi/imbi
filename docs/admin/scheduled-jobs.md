# Scheduled Jobs

**Admin > Global Admin > Scheduled jobs** shows the jobs that
imbi-scheduler fires on a schedule. The scheduler API calls them *tasks*.
The UI calls them *jobs*, so that you do not confuse them with agent
tasks. See [Scheduler tasks](../scheduler/tasks.md) for the full model.

The UI calls the scheduler at `<origin>/scheduler/api` with your Imbi
token.

## Permissions

<!-- BEGIN GENERATED: scripts/docs_permissions_subset.py scheduled_task: -->

| Permission | Lets you | Roles that have it |
|---|---|---|
| `scheduled_task:read` | View scheduled tasks and their run history | `admin`, `developer`, `default`, `readonly`, `imbi-scheduler`, `imbi-workflows` |
| `scheduled_task:create` | Create scheduled tasks | `admin`, `developer`, `imbi-scheduler`, `imbi-workflows` |
| `scheduled_task:write` | Update, pause, and resume scheduled tasks | `admin`, `developer`, `imbi-scheduler`, `imbi-workflows` |
| `scheduled_task:delete` | Delete scheduled tasks | `admin`, `developer`, `imbi-scheduler`, `imbi-workflows` |
| `scheduled_task:run` | Run scheduled tasks on demand and cancel in-flight runs | `admin`, `developer`, `imbi-scheduler` |
| `scheduled_task:admin` | Manage other principals' and system scheduled tasks | `admin`, `imbi-scheduler` |

<!-- END GENERATED -->

You can manage the jobs that you created. To manage other jobs, and all
system jobs, you need `scheduled_task:admin`. The run history of a job
has the same rule. The page shows only the actions that you can do.

## The job list

Each row shows the schedule, the call, the next run, the state of the
last run, and the last 8 runs as dots. The switch pauses or resumes the
job.

Use the filters to show **All**, **System**, **Last run failed**, or
**Paused** jobs.

## Job states

| State | Meaning |
|---|---|
| Succeeded | The target accepted the call |
| Already running | The target answered `409`: the previous run was not finished. The work did not fail. If you see this often, make the interval longer |
| Failed | The call failed, or the target answered with an error |
| Timed out | The target did not answer in the timeout |
| No effect | The gateway accepted the delivery and then dropped it (`204`) |
| Skipped | The scheduler did not fire the job, for example because it could not resolve the identity |
| Paused | The job is disabled |

The scheduler records an "Already running" run as `failed` with
`http_status` `409`. The UI shows it in amber.

## Job detail

The detail page has these actions: **Run now**, **Pause** or
**Resume**, **Edit**, and **Delete**. It has three tabs:

- **Run history**: the last 50 runs, with the status code and the
  start of the response.
- **Definition**: the trigger, the identity, the target, and the
  failure policy.
- **Dry run**: the request that the job sends, rendered without sending
  it.

## System jobs

A system job has a **system** badge. Imbi creates it when it is missing
and never changes your edits. On a system job you can change only the
schedule, the timezone, and the failure policy.

!!! note
    If you delete a system job, the scheduler creates it again with the
    default schedule at its next start. To stop a system job, pause it.

## Create or edit a job

1. Click **New job**, or click **Edit** on a job.
2. Set the trigger: **Cron**, **Interval**, **Calendar**, or **Once**,
   and the timezone. **Once** takes a UTC time.
3. Set the target: an **Imbi API** call, or a **Gateway webhook**. An
   Imbi API call runs as the scheduler service account, and you are
   recorded as accountable.
4. Set the failure policy: timeout, retries, backoff, and the late-start
   grace time.
5. Click **Create job** or **Save Changes**.

An edit sends a JSON Patch with only the fields that you changed.

## Related pages

- [Scheduler tasks](../scheduler/tasks.md)
- [Maintenance](maintenance.md)
