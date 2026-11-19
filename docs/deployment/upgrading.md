# Upgrading

This page tells you what to do when you upgrade Imbi. The first part is the
procedure for every upgrade. The second part has one section for each
release that needs manual steps, newest release first.

Use 2.41.0 or later for a new install.

## Upgrade procedure

1. Read the release sections below, from the release after your current
   version up to the target release. If you skip releases, you must do the
   steps of each release that you skip.
2. Set the image tag to the target release. Do not use `latest` in
   production.
3. Do the steps that the release sections tell you to do before you deploy.
4. Deploy the new image.
5. Run the setup commands that the release sections name, in this order:

    ```bash
    imbi-api setup-permissions
    imbi-api setup-service-accounts
    imbi-api setup-clickhouse
    imbi-api setup-prompts
    ```

    All four commands are idempotent. If you skip releases, run each command
    one time. One run applies the changes of all the releases.
    `setup-permissions` must run before `setup-service-accounts`, because
    `setup-service-accounts` gives each internal service account a role by
    name. When more than one organization exists, run
    `imbi-api setup-service-accounts --organization <slug>`.
    [Applying Upgrades](../getting-started/setup.md#applying-upgrades)
    tells what each command does.

6. If a release adds an Iggy stream, restart the Iggy connectors runtime
   (iggy-connect) after `setup-clickhouse`. The runtime reads its sink
   configuration one time, at startup. The sink writes to the ClickHouse
   table that has the same name as the stream, so the table must exist
   first.
7. Do the other steps of the release sections, for example the maintenance
   operations.

imbi-api applies the PostgreSQL graph schema and the relational schemas
(`tickets`, `workflows`, `workflow_runtime`, `secrets`, `harness`,
`ai_runtime`) at startup. You do not run a command for them.

### Where to run the commands

Run each command in a container of the new release that has the imbi-api
environment.

| Deployment | Command |
|---|---|
| Kubernetes | `kubectl -n <namespace> exec deploy/<deployment> -- imbi-api <command>` |
| Docker Compose | `docker compose exec imbi imbi-api <command>` |
| Docker | `docker exec <container> imbi-api <command>` |

On Kubernetes, the Deployment name is the release name, or
`<release>-imbi` when the release name does not contain `imbi`. Use the
`all` mode release, or the `api` mode release when you run the services
separately.

To restart iggy-connect:

| Deployment | Command |
|---|---|
| Kubernetes | `kubectl -n <namespace> rollout restart deployment/<deployment>-connect` |
| Docker Compose | `docker compose restart iggy-connect` |
| Docker | `docker restart <iggy-connect container>` |

## Releases with no manual steps

These releases need only the new image: 2.39.1, 2.37.0, 2.35.1, 2.34.0,
2.30.0, 2.29.0 to 2.29.4, 2.27.0, 2.26.1, 2.21.0, 2.21.1.

## Unreleased: handoff and waiting on me (ADR 0028)

Set the version of this section when the release is cut.

1. **Before you deploy**, deploy 2.57.0 everywhere and let its rollout
   finish.
2. Deploy the new image. There is no setup command. At start, imbi-api
   adds the column `tickets.tickets.handed_off_at` and two indexes for
   Waiting on me, `tickets_owner_open_idx` and
   `tickets_assignee_open_idx`. The index build stops writes to
   `tickets.tickets` while it runs. A pod of the previous release does
   not use or drop them. A handoff writes values that the person ticket release reads
   already: the request status `withdrawn` and the event types
   `handed_off`, `assignee.changed`, and `request.withdrawn`.
3. Deploy the runner image when you like, before or after imbi-api. An
   agent gets the `hand_off` tool from the new runner. Against an older
   imbi-api, the tool tells the agent that the handoff failed, and the
   ticket stays with the agent.

While pods of both releases run:

- A pod of the previous release reads a handed-off ticket as a plain
  agent ticket or person ticket. A withdrawn request is not open for it,
  and its history of a new session shows the request as withdrawn.
- Do not hand a ticket back to an agent until the rollout is done when
  the ticket had agent sessions before. A pod of the previous release
  counts the task timeout from the first session of the ticket, so its
  heartbeat can close the ticket with `exceeded_ceiling`
  (`task_timeout`). The new release counts from the first session after
  the last handoff.
- The new UI shows **Hand off** on a ticket. When a pod of the previous
  release takes the request, it fails with `404`; try again.
- When an agent hands off its ticket, the runner keeps the chain until
  it finishes. The chain then has an open ticket, so it goes to
  `fencing`, as for a paused ticket.
- `GET /tickets/waiting` now counts what waits on the caller, and
  returns the three lists with `?lists=true`. Before, it
  counted every ticket of the organization with an open request. While
  pods of both releases run, the badge can show either count, and the
  new **Waiting on me** page shows empty lists when a pod of the
  previous release answers. The **Waiting on people** tile of the agent
  dashboard keeps the count for the organization.

## 2.57.0

This release adds person tickets and removes the old names of ADR 0028
that 2.56.0 (release B) kept for the pods of 2.55.0. No pod of 2.56.0
uses them.

1. **Before you deploy**, deploy 2.56.0 everywhere and let its
   rollout finish. A pod older than 2.56.0 uses the objects that this
   release drops.
2. **Before you deploy**, make sure that 2.56.0 copied every event of
   `agent_task_events` to `ticket_events`. This release drops the old
   table. The result must be `0`:

    ```sql
    SELECT uniqExact(task_id, seq) FROM imbi.agent_task_events
     WHERE (task_id, seq) NOT IN (SELECT ticket_id, seq FROM imbi.ticket_events)
    ```

   If it is not `0`, run `imbi-api setup-clickhouse` in a 2.56.0 pod,
   then run the query again.
3. **Before you deploy**, change each scheduled task whose `api` target
   path has `/agent-tasks` to use `/tickets`. This release removes the
   `/organizations/{org}/agent-tasks` paths, so a run of such a task
   gets `404` and fails. Find the tasks in PostgreSQL (the schema is
   `IMBI_SCHEDULER_SCHEMA`, default `scheduler`):

    ```sql
    SELECT slug, organization, target ->> 'path' AS path
      FROM scheduler.tasks
     WHERE target ->> 'kind' = 'api'
       AND (target ->> 'path' LIKE '%/agent-tasks%'
            OR target ->> 'path' LIKE '%{{%'
            OR target ->> 'path' LIKE '%{\%%')
    ```

   The path is a Jinja2 template, so the query also returns each path
   that has a template expression (`{{` or `{%`). Such a path can render
   a different path on each run. Read its template: check each branch
   and each value that the task gets when it runs (for example `now`),
   not only one rendered path. If any of them can render an
   `/agent-tasks` path, change the task too. If the query returns no
   rows, no task uses the old path. To change a
   task, send a JSON Patch of `/target/path` to
   [`PATCH /tasks/{slug}`](../scheduler/tasks.md) on imbi-scheduler.
   Also change the scripts that call the old path.
4. Deploy imbi-api first, then imbi-mcp, the harness runners,
   imbi-gateway, imbi-slackbot, and imbi-workflows. At its first start,
   imbi-api:
   - moves the primary keys of `harness.chains` and `harness.claims` to
     `root_ticket_id` and `ticket_id`, and drops the old columns
     (`root_task_id`, `task_id`), the trigger that kept them equal, and
     the function `harness.mirror_ticket_id()`,
   - changes the origin kind `task` to `ticket` in each child ticket that
     a 2.55.0 pod made after the last start of a 2.56.0 pod, and
   - adds `tickets.tickets.assignee_kind` (default `agent`) and
     `tickets.tickets.assignee`, makes `agent_id`, `agent_version`, and
     `service_account_id` nullable, and adds three checks: the assignee
     kind, the columns of each kind, and the statuses of each kind.
     Every existing ticket is an agent ticket.

   You do not run a command for this. The harness change locks
   `harness.chains` and `harness.claims` while it builds the two new
   primary keys. The person ticket step reads the whole tickets table to
   validate the checks, and stops writes to `tickets.tickets` while it
   runs.
5. Run `imbi-api setup-clickhouse` in a new imbi-api pod (pick the pod by
   name, as for 2.54.0). It drops the `agent_task_events` table. There
   is no iggy-connect restart: 2.56.0 removed the old stream.
6. Do not make person tickets until every imbi-api pod runs this
   release. Only a new pod can make one. A 2.56.0 pod reads one, but
   some of its writes fail on one (see below).

While pods of both releases run:

- If you run `setup-clickhouse` in a 2.56.0 pod, it makes an empty
  `agent_task_events` table again. Run it again in a new pod to drop it.

If a person ticket exists while pods of both releases run:

- A 2.56.0 pod reads a person ticket: the ticket list, the ticket,
  and its relations show it with no agent. 2.56.0 makes the agent
  columns optional in its responses for this reason.
- A 2.56.0 pod that closes a ticket with a `done_*` outcome, and the
  ticket gates a held person ticket, tries to move the person ticket to
  `queued`. The check refuses that, so the whole close fails with 500,
  also when the agent of the ticket reports its outcome. The close
  works when a new pod takes the retry.
- A 2.56.0 pod that pauses, resumes, or cancels a person ticket fails
  with 500, and the ticket does not change.
- No runner claims a person ticket: the claim query reads only `queued`
  tickets, and a person ticket is never `queued`.
- The events of a person ticket go to ClickHouse with an empty
  `agent_id` and `agent_version` 0, from pods of both releases.
- The 2.56.0 UI shows a person ticket with no agent name. It cannot
  make one.

## 2.56.0

This release is release B of ADR 0028. It removes the old names that no
pod of 2.55.0 uses, and adds parent tickets and gating dependencies. The
old objects that 2.55.0 still reads stay until the next release removes
them.

1. **Before you deploy**, deploy 2.55.0 everywhere and let its rollout
   finish.
2. **Before you deploy**, make sure that no MCP client calls a tool with
   an old name (`*_agent_task_*`). imbi-mcp gets its tools from the API
   document. This release removes the `/organizations/{org}/agent-tasks`
   paths from that document and removes the `/harness/tasks` paths, so
   the old tools go. Use the `*_ticket_*` tools.
3. Deploy imbi-api first, then imbi-mcp, the harness runners,
   imbi-gateway, imbi-slackbot, and imbi-workflows. At its first start,
   imbi-api:
   - drops the `agent_runtime` schema and its views, which only 2.53.0
     used,
   - makes the child origin kinds `task` and `ticket` one kind in the
     unique index of ticket idempotency keys, and changes `task` to
     `ticket` in every ticket (each start does this again for a child
     ticket that a 2.55.0 pod made during the rollout), and
   - adds a unique index that makes the run origin kinds
     `task_completed` and `ticket_closed` one kind,
   - adds `tickets.tickets.parent_id` and its foreign key. Before it
     adds the key, it sets the parent of each child ticket that an agent
     made from its own ticket. This runs one time. A trigger gives the
     parent to a child that a 2.55.0 pod makes during the rollout, and
   - adds `tickets.ticket_dependencies.gates` (default `false`), so
     existing dependencies stay links only.

   You do not run a command for this. The index changes lock writes to
   `tickets.tickets` and `workflow_runtime.runs` while they run.
4. As soon as the first new imbi-api pod is up, run
   `imbi-api setup-permissions` in that pod (step 5), then
   `imbi-api setup-clickhouse` in the same pod (pick the pod by name, as
   for 2.54.0). `setup-clickhouse` copies the events of
   `agent_task_events` that `ticket_events` does not have. No pod writes
   to the `agent_task_events` stream since 2.54.0, but iggy-connect reads
   it until step 6, so step 6 checks the copy again. This release reads
   only `ticket_events`, so until the copy is done a new pod shows an
   incomplete log for a ticket that was archived before 2.54.0. The old
   table has no TTL, so the copy can be large. Before you deploy, count
   its rows:

    ```sql
    SELECT count() FROM imbi.agent_task_events
    ```

   Then make sure that every event was copied. The result must be `0`:

    ```sql
    SELECT uniqExact(task_id, seq) FROM imbi.agent_task_events
     WHERE (task_id, seq) NOT IN (SELECT ticket_id, seq FROM imbi.ticket_events)
    ```

5. `imbi-api setup-permissions` runs first because the copy can be
   slow, and 2.55.0 pods accept the new names. It gives each role that
   has an `agent_task` permission, custom roles too, the `ticket`
   permission with the same action, then removes the `agent_task` permissions. An API key scope
   that names an `agent_task` permission keeps working. A new pod does
   not accept an `agent_task` permission of a role, so until this
   command runs, a custom role that has only the `agent_task` name of a
   permission (2.54.0 gave the `ticket` names to the default roles only)
   cannot use the tickets in the UI. Before you deploy, find such roles:

    ```cypher
    MATCH (r:Role)-[:GRANTS]->(p:Permission)
    WHERE p.name STARTS WITH 'agent_task:'
      AND NOT EXISTS { MATCH (r)-[:GRANTS]->(q:Permission)
                       WHERE q.name = 'ticket:' + substring(p.name, 11) }
    RETURN r.slug, p.name
    ```

   If the query returns no rows, nobody loses access.
6. When the imbi-api rollout is complete, restart iggy-connect. The
   `agent_task_events` stream is not in its configuration anymore.
   After the restart, run the check of step 4 again. If the result is
   not `0`, an event that was still in the stream arrived after the
   copy: run `imbi-api setup-clickhouse` again in an imbi-api pod. The
   copy adds only the missing events.
7. Change each scheduled job whose `api` target path has `/agent-tasks`
   to use `/tickets`. The old path still works in this release, but the
   next release removes it.

While pods of both releases run:

- A new pod writes `ticket` as the origin kind of a child ticket, and
  `ticket_closed` as the origin kind of a run that a closed ticket
  starts. 2.55.0 reads both. When a 2.55.0 workflow sweep retries a
  closed ticket whose run a new pod started, the unique index stops a
  second run. The 2.55.0 pod then logs that the task did not start the
  workflow, until a new pod takes the retry.
- The harness tables keep `chains.root_task_id` and `claims.task_id`,
  which 2.55.0 reads. This release uses only `root_ticket_id` and
  `ticket_id`; a trigger fills the old columns. The next release moves
  the keys and drops the old columns, the trigger, the
  `agent_task_events` table, and the `/agent-tasks` paths.
- Do not add gating dependencies until every imbi-api pod runs this
  release. A 2.55.0 pod does not release the dependents of a ticket
  that it closes, so they stay `held`. To release such a ticket, remove
  the gating dependency, or add it again as a link only.

## 2.55.0

1. **Before you deploy**, deploy 2.54.0
   everywhere and let its rollout finish. This release writes a value
   that only 2.54.0 and later can read: the event type
   `ticket.created`.
2. Deploy the new image. There is no setup command and no schema
   change.

This release also reads ticket statuses (`held`, `open`,
`in_progress`), the request status `withdrawn`, and event types
(`reopened`, `assignee.changed`, `parent.changed`, `handed_off`,
`request.withdrawn`) that no release writes yet. A later release writes
them, and a pod of this release can then read its rows during that
rollout. Child tickets keep the origin kind `task`, and workflow runs
that a closed ticket starts keep the origin kind `task_completed`, until
release B.

## 2.54.0

1. **Before you deploy**, deploy 2.53.0 everywhere
   and let its rollout finish. That release skips a relational table
   that is a view. Without it, an imbi-api pod of an older release that
   restarts during this rollout cannot start.
2. Deploy imbi-api first, before the harness runners, imbi-gateway,
   imbi-slackbot, imbi-mcp, and imbi-workflows. At its first start,
   imbi-api moves the `agent_runtime` tables to the new `tickets` schema
   with new names, in one transaction, and leaves views under the old
   names for the pods of the previous release. It also adds
   `root_ticket_id` to `harness.chains` and `ticket_id` to
   `harness.claims`, with a trigger that keeps them equal to the old
   columns. You do not run a command for this. The move holds an
   exclusive lock on the task tables while it runs; it moves no rows.
3. As soon as the first new imbi-api pod is up, run
   `imbi-api setup-clickhouse` in that pod to create the
   `ticket_events` table. Pick the pod by name, from the new
   ReplicaSet: `kubectl exec deploy/imbi-api` can select a pod of the
   previous release, which does not know the table. Until the table
   exists, a new pod cannot read the log of an archived ticket.
4. When the imbi-api rollout is complete, restart iggy-connect (see
   [Where to run the commands](#where-to-run-the-commands)): the
   `ticket_events` stream (topic `tickets`) is new, and the sink reads
   the stream list only at startup. Ticket events now go to
   `ticket_events`. Imbi reads `agent_task_events` and `ticket_events`
   together until a later release copies the old table.
5. Run `imbi-api setup-permissions`. It adds the `ticket:read`,
   `ticket:create`, `ticket:manage`, `ticket:resolve`, and
   `ticket:delete` permissions and gives them to each default role that
   has the `agent_task` permission with the same action. Every check
   accepts either name, so a custom role with only `agent_task`
   permissions keeps working.
6. **Until the imbi-api and imbi-workflows rollouts are complete**, do
   not activate a workflow with a **Ticket closed** trigger:
   - A pod of the previous release can take a ticket closure from the
     trigger outbox and start only the **Task completed** workflows.
     The **Ticket closed** run then never starts.
   - An imbi-workflows pod of the previous release does not know the
     **Ticket closed** step. It cannot start such a run, and the run
     stays queued until a new pod claims it.

   Also, while pods of both releases run, a pod of the previous release
   can show an incomplete log for a ticket that a new pod archived,
   because it reads only `agent_task_events`. No events are lost; the
   full log shows once the rollout is complete.
7. The API serves tickets at `/organizations/{org_slug}/tickets` and
   `/harness/tickets`. The `/agent-tasks` and `/harness/tasks` paths
   still work, with the same operation ids, and are marked deprecated. A
   later release removes them.

## 2.53.0

imbi-api creates the `ai_runtime` schema, which records each AI model
call, when it starts.

1. Run `imbi-api setup-permissions`. It adds `prompt:run` and gives it to
   the `admin`, `developer`, and `imbi-workflows` roles. The engine needs
   it to run an LLM Call step, and a person needs it to activate a
   workflow with one. It also adds
   `admin:maintenance:ai-model-calls-prune` and gives it to the
   `imbi-scheduler` role. The new `ai-model-calls-prune` system task runs
   daily at 02:30 UTC, and without the permission each run gets a `403`.
2. In **Admin > Global Admin > AI Models**, set **Structured output** on
   each generative model that supports it. The switch is off for every
   existing model. An LLM Call step with output fields cannot use a
   model with the switch off. See
   [Structured output](../admin/ai-models.md#structured-output).
3. To use Gemini on Google Vertex AI in an LLM Call step, set an API key
   on the Vertex provider. The runtime IAM role does not work for these
   calls.
4. **Before you deploy**, find each agent whose model has no enabled
   catalog entry, or is restricted to teams that do not include the
   agent's owner team. When a runner claims a task of such an agent,
   imbi-api now closes the task with `failed_external` and the reason
   `model_not_allowed`. Enable a catalog model with that model ID, add
   the owner team to the model, or point the agent at a prompt version
   with another model. Decision prompt runs now check the teams of a restricted model
   too. See [Team access](../admin/ai-models.md#team-access).
5. imbi-assistant now checks the model of each new conversation. A user
   who is not an admin gets `403 model_not_allowed` for a model that is
   not an enabled catalog model, or that is restricted to teams the user
   is not in. `IMBI_ASSISTANT_MODEL` still works when it is not in the
   catalog. When the model of the system prompt of the assistant or the
   Slack bot is restricted, they use it only for members of an allowed
   team. Other users get the configured model. An enabled model that is
   not restricted is used for all users.
6. Archiving or deleting a project now deletes its SonarQube project only
   when the linked key is `<owning-team-slug>:<project-slug>`, and only
   when no other Imbi project links the key. Imbi skips any other key.
   Do not delete a skipped key that another Imbi project links: that
   project still uses it. For other skipped keys, make sure that no
   other project uses the SonarQube project, then delete it in
   SonarQube yourself.
   Linking a SonarQube key that another project holds in the same
   integration now gets a `409`,
   and only an admin can change a verified SonarQube key. See
   [SonarQube lifecycle](../plugins/sonarqube.md#lifecycle).
7. When the request of imbi-api to the provider gets no answer (a read
   timeout or a lost connection), imbi-api now returns
   `provider_outcome_unknown`, and the LLM Call step fails and is not
   retried. Before, the engine retried it, and the provider could bill
   a second call. When the engine loses the response of imbi-api, it
   asks again with the same idempotency key and gets the recorded
   result. It does not make a second call. See
   [LLM Call](../admin/workflows.md#llm-call).
8. Renaming an organization now moves its `agents/` and `workflows/`
   prompts to the new slug, and updates the agents and LLM Call steps
   that use them. A prompt that an earlier rename left under an old slug
   is not moved. If you renamed an organization that has agents, check
   that each agent still resolves its prompt. An agent can no longer
   use an org-owned prompt of another organization (`422` on save,
   `409` on restore).
9. AI Models has a new **Forced tool choice** switch. It is on by
   default, so existing models do not change. Turn it off for an
   Anthropic or Bedrock model that refuses a forced tool choice, for
   example a model with extended thinking. See
   [Forced tool choice](../admin/ai-models.md#forced-tool-choice).

## 2.51.0

1. A task whose agent stops without calling `report_outcome` now fails
   with `failed_external` and the reason `no_outcome_reported`. Before,
   it closed as `done_acted` when the agent called a tool that changes
   data, else as `done_nothing_to_act_on` (`no_mutating_tool_call`). A
   workflow `agent` step on such a task now takes `Failed`. Check the
   prompts of agents that do not call `report_outcome`.

## 2.50.0

1. Scheduled tasks now run with only the permissions of the person
   accountable for them (who last changed the task, else who made it),
   and only in organizations where that person is a member. A task whose
   person has left an organization, lost a permission, or been
   deactivated now gets a `403` there. After you deploy, look for failed
   scheduler runs with a `403`. Have a current member of the organization
   take over each task that is still needed. An admin who changes or
   resumes a task becomes accountable for it, and an admin's task is not
   limited, so read its target before you resume it. See
   [Targets](../scheduler/tasks.md#targets).
2. Run `imbi-api setup-permissions`. It adds
   `admin:maintenance:marketplace-sync` and gives it to the
   `imbi-scheduler` role. The new `marketplace-sync` system task starts
   that maintenance operation every 6 hours, and without the permission
   each run gets a `403`. See
   [System tasks](../scheduler/tasks.md#system-tasks).
3. **Before you deploy**, delete every scheduled task whose `api` target
   path is under `/auth`. The scheduler now refuses those paths, and one
   such task stops `GET /tasks` from listing any task. Find them with
   the query below. It uses the default schema `scheduler`. If you set
   `IMBI_SCHEDULER_SCHEMA`, use that schema instead.

    ```sql
    SELECT slug FROM scheduler.tasks
     WHERE target->>'kind' = 'api'
       AND target->>'path' ~ '^/auth([/?#]|$)';
    ```
4. imbi-api now refuses a request body larger than 10 MiB with a `413`
   (`payload_too_large`). File uploads keep their own limit,
   `S3_MAX_FILE_SIZE` plus 1 MiB. If a client sends larger bodies, for
   example a very large SBoM, set `IMBI_API_MAX_REQUEST_BODY_BYTES`.
5. Run `imbi-api setup-clickhouse` to create the `cves` table, and
   `imbi-api setup-permissions` to add `admin:maintenance:cve-sync` and
   give it to the `imbi-scheduler` role. Then restart iggy-connect (see
   [Where to run the commands](#where-to-run-the-commands)): the `cves`
   stream is new, and the sink reads the stream list only at startup.
6. Give the API pods temporary disk for the CVE import. The first
   `cve-sync` imports the full CVE List (about 425 000 records) and needs
   about 1.5 GB of temporary disk in the API pod; later runs need the same
   disk but write only the changed records. In the hosted chart, mount an
   `emptyDir` with a `sizeLimit` of about 3 GiB at the temporary
   directory (`/tmp`, or the directory in `TMPDIR`).
7. imbi-gateway now refuses a request body larger than 25 MiB with a
   `413` (`payload_too_large`). GitHub caps a webhook payload at 25 MB,
   so no GitHub webhook is refused. If a service sends larger webhook
   bodies, set `IMBI_GATEWAY_MAX_REQUEST_BODY_BYTES`. An SBoM that the
   gateway sends on to imbi-api must also fit
   `IMBI_API_MAX_REQUEST_BODY_BYTES` (10 MiB by default).
8. Start the first `cve-sync` from **Admin > Maintenance**. Do not wait
   for the `cve-sync` system task, which runs daily at 01:30 UTC. See
   [CVE catalog](../user-guide/pull-requests-and-dependencies.md#cve-catalog).
9. If the organization's `allowed_tools` lists `Skill` or `Task`, those
   tools no longer go to every agent. Turn on `Skill` or `Agent` in the
   **Built-in** group of the Tools tab of each agent that needs them.

## 2.49.0

1. **Deploy imbi-workflows together with imbi-api.** An older reconciler
   marks the new task-completed trigger bindings `failed`. The trigger
   still works, but it shows as failed.
2. Run `imbi-api setup-permissions`. It adds `workflow:recover` and gives
   it to the `admin` role. The new **Calls with an unknown outcome**
   section on the Workflows page needs it. See
   [Workflows](../admin/workflows.md#calls-with-an-unknown-outcome). It
   also gives the `developer` role `secret_binding:read`.

## 2.47.0

No setup command is required.

1. **Deploy the `imbi-harness` chart together with the runner image.**
   The runner container gets a writable `/tmp` emptyDir (`tmp.sizeLimit`,
   default `1Gi`), and a runner of this release fails at start when
   `/tmp` is not writable. A deployment that does not use the chart and
   has a read-only root filesystem must mount a writable `/tmp` in the
   runner container.
2. **Sentry integrations now create a Sentry release for each new Imbi
   release.** The `release-tracking` capability is on by default. Give
   the Sentry token the **Release: Admin** scope, and set
   `version_format` to the `release` value that the Sentry SDK of the
   application sends. If you do not want Sentry releases, turn the
   capability off on the Integration. See
   [Sentry](../plugins/sentry.md#release-tracking).

## 2.46.0

Run `imbi-api setup-permissions`. It gives the `developer` role
`role:read` and the 13 permissions of production's `default` role that
the seed did not have. imbi-api adds the new `agent_runtime` task columns
and the `task_projects` table when it starts, and moves the project of
each existing task into that table.

1. **Deploy imbi-api before the harness runners.** A runner of this
   release sends the project set of a task, and an older imbi-api refuses
   its secret materializations for project tasks. A resolution made
   before the deploy and materialized after it fails one time.
2. **Deploy the `imbi-harness` chart together with the runner image.**
   The runner pod gets a new `plugins` emptyDir (`plugins.sizeLimit`,
   default `1Gi`), and a runner of this release fails at start when
   `/run/plugins` is missing.

## 2.45.0

No setup command is required. imbi-api adds the `hostnames` column of
`harness.egress_destinations` when it starts.

1. **The `imbi-harness` chart in `deployment` mode needs Kubernetes 1.32
   or later.** Admission policies now let a runner delete and patch only
   its own pod. Check the cluster version before you upgrade the chart.
2. The egress proxy for host name egress destinations is optional and
   off. To turn it on, follow
   [Agent runners](agent-runners.md): put the token key in a Secret, set
   `egressProxy.enabled` and `egressProxy.secret.existingSecret` in every
   harness release, and set `IMBI_HARNESS_EGRESS_PROXY_SECRET` on imbi-api
   to the same key. To roll back, set `egressProxy.enabled: false` in
   every release.
3. The MCP servers in **Admin > Assistant** no longer reach agents, and
   the `mcp_server` secret purpose is retired. The broker refuses each
   request for it. Optionally, delete the grants that still name
   `mcp_server` in **Admin > Secrets**, and switch off agent tools such as
   `zoekt.*` under **Not in the catalog** on the agent **Tools** tab.

## 2.44.0

imbi-api, imbi-assistant, and imbi-slackbot can use the short-lived token
of an AI provider (workload identity) to call Anthropic. All of these steps
are optional. If you do not do them, each service continues to use
`ANTHROPIC_API_KEY`.

1. Run `imbi-api setup-permissions`. It adds the `ai_provider:token`
   permission and the `imbi-assistant` and `imbi-slackbot` roles.
2. `imbi-api setup-service-accounts` creates the `imbi-assistant` and
   `imbi-slackbot` service accounts. It stores the values of
   `IMBI_ASSISTANT_API_TOKEN` and `IMBI_SLACKBOT_API_TOKEN` on imbi-api as
   their API keys. If a value is not set, the command makes a key and
   prints it one time only: copy the key from that output. A later run
   does not change the key and does not print it again. Set the same
   values on imbi-assistant (`IMBI_ASSISTANT_API_TOKEN`) and
   imbi-slackbot (`IMBI_SLACKBOT_API_TOKEN`). If you lose a key, rotate
   it or create a new one on the service account page
   ([API keys](../admin/service-accounts.md#api-keys)).
3. Set `IMBI_AI_PROVIDER_API`, `IMBI_AI_PROVIDER_ASSISTANT`, and
   `IMBI_AI_PROVIDER_SLACKBOT` on imbi-api to the AI provider IDs. See
   [AI Models](../admin/ai-models.md#imbi-services).

By default, agent runners do not send the model key to an `http://` model
upstream.
If the **Base URL** in **Agents > Settings > Platform** of an organization
uses `http://`, its tasks fail with `model_upstream_insecure` after the
upgrade. In each such organization, change the URL to `https://`. For a
protected in-cluster upstream only, turn on **Allow http://** instead. Then
click **Save version**. See
[Agent runners](agent-runners.md#5-configure-the-model-key).

The **Opened** and **Reviewers** columns of the Open Pull Requests report
need these steps:

1. Run `imbi-api setup-clickhouse`. It adds the
   `pull_request_review_requests` and `pull_request_reviews` tables.
2. Restart iggy-connect, so that the sink reads the two new streams.
3. Subscribe the GitHub webhook or App to **Pull request reviews** events,
   and add a webhook rule that runs `github#sync_pull_request_reviews`. If
   an existing `pull_request` rule filters actions, add
   `review_requested` and `review_request_removed`.
4. Optional: click **Sync Pull Requests** on a project to fill in the
   reviewers of its open pull requests.

Optional: to remove pull request rows that GitHub no longer lists, resync
the pull request history of the affected projects.

## 2.43.0

1. Run `imbi-api setup-permissions`. It gives the `admin` role
   `agent_task:delete`, which the new **Delete** button on a closed agent
   task needs.
2. Optional: to show old drift in red on the projects list, set
   `VITE_DRIFT_STALE_AFTER` (for example `7d`) on the UI service, or the
   Helm value `service.ui.driftStaleAfter`. When it is empty, drift stays
   amber.
3. Remove `IMBI_OAUTH_ALLOW_INSECURE_URLS` from your environment, if it is
   set. Imbi does not have this setting now.

## 2.41.0

Upgrade from 2.40.0 as soon as you can. In 2.40.0, each Imbi service stored
only its first Iggy message after it started. Iggy discarded the others
without an error, so ClickHouse got no new webhook events, pull requests,
tags, commits, SBOM components, or operations log rows.

1. Deploy the 2.41.0 image to every Imbi service.
2. Check that Iggy stores new messages. Compare the gateway's
   `imbi_iggy_published_total{stream="events",topic="gateway"}` with the
   offset from `iggy message poll --last events gateway 0` for two minutes.
   Both must increase by the same number.
3. Run **Sync PRs** and **Sync Commits & Tags** again for each project, to
   restore the rows that 2.40.0 lost. Webhook events and SBOM uploads from
   that period cannot be restored.

Do not install 2.40.0 on a new system.

## 2.40.0

1. Run `imbi-api setup-permissions`. It gives the `developer` role
   `project:deployment:read`, `project:deployment:write`,
   `project:commits:read`, `project:commits:write`,
   `project:pull-requests:read`, `project:pull-requests:write`, and
   `operations_log:read`. It gives the `default` and `readonly` roles
   `project:deployment:read`, `project:commits:read`, and
   `project:pull-requests:read`.
2. Make sure that each platform administrator who manages deployments is a
   member of each organization of those projects. The deployment,
   commit-sync, and pull-request-sync routes now use only the role in the
   organization of the path. A platform administrator who is not a member
   gets `403 organization_forbidden`. See
   [Roles and Permissions](../admin/roles-and-permissions.md#permissions-across-organizations).
3. Examine the `IMBI_AUTH_PASSWORD_*` and `IMBI_AUTH_RATE_LIMIT_*` values
   in your environment. Imbi now reads them. Before, it used the defaults.
   Remove `IMBI_AUTH_RATE_LIMIT_API_KEY`. Imbi does not have this setting
   now. The password rules now also apply when an administrator creates a
   user with a password.
4. Examine the `allowed_domains` option of your login provider. Imbi now
   rejects a sign-in from a domain that is not in a list that is not empty.
   See [Authentication](../admin/authentication.md#sso-login-providers).
5. Check each client credential that has scopes, and each client that
   sends `scope` to `POST /auth/token`. A client-credentials token now
   gets only the permissions in its scopes, as an API key does. Before,
   it got all the permissions of the roles of the service account. The
   seeded `imbi-scheduler` and `imbi-workflows` credentials have no
   scopes, so they do not change.
6. **Helm chart: the chart now runs in production mode.** The new
   `environment` value defaults to `production`, and the chart sets
   `ENVIRONMENT` and `IMBI_API_ENVIRONMENT` to it. In production mode Imbi
   does not generate `IMBI_AUTH_JWT_SECRET`, `IMBI_AUTH_ENCRYPTION_KEY`, or
   `IMBI_CONFIG_ENCRYPTION_KEY` and fails without them, and the auth cookies
   get the `Secure` flag. Before you upgrade:
    - Set `auth.configEncryptionKey` to a new Fernet key, or add a
      `config-encryption-key` key to your `existingSecret`. The chart
      refuses to render without it. Before this release, each process of a
      chart install generated its own key, so Imbi cannot decrypt the
      configuration secrets saved before the upgrade (AI provider keys, MCP
      server credentials). Enter them again after the upgrade.
    - Set `service.publicApiUrl` in `all` and `ui` mode. The chart sets
      `VITE_API_URL` to it and refuses to render without it.
    - `iggyConnect.enabled` now defaults to `true`. Set `iggyConnect.apiKey`,
      `iggyConnect.iggy.address`, and `iggyConnect.iggy.password`, or set
      `iggyConnect.enabled: false` if you run the connectors runtime
      yourself.
    - In `gateway` mode, set `gateway.serviceAccount.token` (or the
      `gateway-sa-token` key of `existingSecret`).
    - In `slackbot` mode, set `slackbot.botToken`, `slackbot.appToken`, and
      `assistant.anthropicApiKey`, or the matching `existingSecret` keys.

    New chart values: `environment`, `auth.configEncryptionKey`,
    `externalValkey.url`, `extraEnv`, `extraEnvFrom`, `slackbot.*`,
    `iggyConnect.extraEnv`, and `iggyConnect.extraEnvFrom`. See
    [Kubernetes Deployment](kubernetes.md).
7. **Container entrypoint.** `gateway` mode now also requires
   `CLICKHOUSE_URL`, `IGGY_URL`, `IMBI_AUTH_ENCRYPTION_KEY`, and
   `IMBI_GATEWAY_API_TOKEN`. `slackbot` mode now also requires
   `IMBI_AUTH_JWT_SECRET`. The image no longer exposes port 2019.
8. **`setup-clickhouse` exits with status 1** when a DDL statement fails. It
   still runs the other statements first. An upgrade script must check
   this status, for example with `set -e`, and stop the upgrade when it
   is not 0.
9. Optional: the **Semantic versioning** format now accepts a leading `v`
   (`v1.2.3`). An organization or a project type that turned it on before
   this release keeps the old pattern. To store the new pattern, click
   **Save changes** on **Default Settings**. For a project type, turn
   **Semantic versioning** off and on again, then save it. See
   [Catalog settings](../admin/catalog-settings.md).
10. If you use a `config.toml` file, examine it against your environment
    variables and `.env` entries. An environment variable or `.env` entry
    now wins over the same key in `config.toml`. Before, a `[server]` or
    `[storage]` key in the file won.
    Before you upgrade, correct or remove each `[server]` and `[storage]`
    value that is not valid for its setting. Before, Imbi ignored the file
    when such a value failed validation. Now the service does not start,
    or storage fails. An environment variable or `.env` entry for the same
    key replaces the file value, so the file value is then not checked.
    Also, every service now reads the `[auth]`, `[clickhouse]`,
    `[embeddings]`, `[plugins]`, `[postgres]`, `[releases]`, `[ssl]`, and
    `[valkey]` sections, and imbi-api reads `[email]`. Before, the services
    ignored them. Remove the keys that you do not want to apply. See
    [`config.toml`](../api/configuration.md#configtoml).
11. AWS is no longer a login provider. An AWS login provider does not show
    on the login page after the upgrade. Before you upgrade, make sure that
    no user signs in only through AWS. Users still connect AWS at
    **Settings > Connections**.
12. Find the webhook rules whose handler is in the old dotted form. The
    gateway skips these rules, and a PATCH of their webhook gets 400 until
    you correct or remove each one:

    ```cypher
    MATCH (r:WebhookRule) WHERE NOT r.handler CONTAINS '#'
    RETURN r.handler, count(*)
    ```

    Change each handler to the `<plugin>#<action>` form, or delete the rule.

## 2.39.1

No manual steps. These changes can affect you:

- Imbi now refuses password logins when local authentication is off on the
  **Auth Providers** page. Before 2.39.1, users with a password could still
  log in. If single sign-on fails while local authentication is off, call
  `PUT /admin/local-auth` with `{"enabled": true}` with an admin API key or
  a service account token. See [Authentication](../admin/authentication.md).
- The Google auth provider now rejects a sign-in when the `hd` claim does
  not match `hosted_domain`. Personal Google accounts have no `hd` claim, so
  Imbi rejects them when `hosted_domain` is set.

Do not install 2.39.0 on a new system. Its image cannot create the Iggy
topics, and imbi-api exits at startup. 2.39.1 corrects this.

## 2.39.0

No setup commands. These changes can affect you:

- A request to an organization route gets the permissions of the role in
  the organization of the path only. Before 2.39.0, it got the union of the
  roles in all the organizations of the user. Examine the roles of users
  that are members of more than one organization. See
  [Roles and Permissions](../admin/roles-and-permissions.md#permissions-across-organizations).
- The GitHub Doctor check `homepage-url-match` needs `IMBI_UI_URL` on
  imbi-api. Without it, the check gives one warning and no repair.
  Repository homepages that the lifecycle sync wrote before 2.39.0 are dead
  links. The check reports them as **fail**, and its **Fix** rewrites them.

## 2.38.1

Set `IMBI_INTERNAL_WORKFLOWS_URL` on imbi-api to the in-cluster URL of
imbi-workflows, for example `http://imbi-workflows:8006`. Without it, the
**System health** card on the admin overview shows Workflows as "not
configured".

## 2.38.0

Before you deploy:

- Change each `IMBI_ASSISTANT_SYSTEM_PROMPT` and
  `IMBI_SLACKBOT_SYSTEM_PROMPT` override to Jinja syntax, for example
  `{{ display_name }}` instead of `{display_name}`. Imbi ignores an override
  that it cannot parse.
- Update the API clients of the AI model catalog. The routes moved from
  `/organizations/{org}/ai-providers` and `/organizations/{org}/ai-models`
  to `/ai-providers` and `/ai-models`.

After you deploy:

1. Run `setup-permissions`, `setup-service-accounts`, `setup-clickhouse`,
   and `setup-prompts`.
    - `setup-permissions` adds the `prompt:*`, `agent:*`, `agent_task:*`,
      `workflow:*`, `secret_*`, `harness_pool:read`, and
      `agent_platform_config:write` permissions. It also changes the grants
      of the `imbi-scheduler` and `imbi-gateway` roles and adds the
      `imbi-workflows` role.
    - `setup-service-accounts` adds the `imbi-workflows` service account. In
      `all` mode the container does this step at startup.
    - `setup-clickhouse` adds the `agent_task_events`, `agent_usage`,
      `workflow_runs`, `workflow_run_events`, and `secret_audit_events`
      tables.
    - `setup-prompts` adds the default prompts of imbi-assistant and
      imbi-slackbot. Until you run it, both use their packaged prompts.
2. Restart iggy-connect. The release adds five streams, with the same names
   as the new tables.
3. Edit and save each webhook one time. A webhook made before 2.38.0 has no
   owner, and its `create_agent_task` rules cannot start a task.
4. If an install has a CMS copy of `imbi-slackbot/system`, publish the new
   "Agent Tasks" section of the packaged prompt in that copy.

The release notes also tell you to run `imbi-api setup` again, to give the
organization that setup made an id. You do not have to do this. imbi-api
gives an id to each organization and user that has none, at startup.

Steps for the new features, when you use them:

- **Workflows.** imbi-workflows runs in `all` mode. To run it as its own
  release, see [Kubernetes: Workflows](kubernetes.md#workflows) and set
  `workflows.schedulerUrl`. For schedule and webhook triggers, add the
  `imbi-scheduler` and `imbi-gateway` service accounts to each organization
  that uses them. The `imbi-workflows` role does not include
  `integration:act-as-service`. Give it to the service account if workflows
  deploy projects. See [Workflows](../admin/workflows.md).
- **Agent runners.** Install the `helm/imbi-harness` chart for each runner
  pool. See [Agent Runners](agent-runners.md).
- **Secrets.** The AWS secrets provider uses the AWS identity of imbi-api.
  The Helm chart does not give imbi-api an AWS identity. Add one, for
  example with IRSA or EKS Pod Identity. See [Secrets](../admin/secrets.md).
- **Metrics.** The Helm chart adds Prometheus scrape annotations. If you do
  not use the chart, add the annotations yourself. See
  [Operations: Metrics](operations.md#metrics).

## 2.36.0

Run `setup-clickhouse`. It adds the `email_audit` table. Before 2.36.0,
Imbi stored no password-reset email audits.

## 2.35.0

Restart iggy-connect. The release moves every ClickHouse write to Iggy and
adds 14 streams. Without the restart, Imbi publishes to the new streams and
nothing writes them to ClickHouse.

## 2.33.0

After you deploy, run these maintenance operations from
**Admin > Global Admin > Maintenance**, in this order:

1. **Report Re-stamped Commit Push Times (dry run)**
   (`commit-pushed-at-check`)
2. **Repair Re-stamped Commit Push Times** (`commit-pushed-at-repair`)

They restore the commit push times that the commit sync overwrote.

## 2.32.3

`IMBI_API_URL` must include the scheme, for example
`https://imbi.example.com/api`. A value without a scheme stops the service
at startup.

## 2.32.2

On Docker and Docker Compose, rename `ACTIONS_IMBI_TOKEN` to
`IMBI_GATEWAY_API_TOKEN`. The Helm chart sets the new name from the
existing `gateway-sa-token` secret key, so Helm installs need no change.

## 2.32.1

imbi-gateway reads the URL of imbi-api from `IMBI_INTERNAL_API_URL`. Set it
when the gateway runs as its own service. 2.32.2 removes the
`ACTIONS_IMBI_URL` fallback.

## 2.32.0

This release adds Apache Iggy. Before you deploy:

1. Deploy an Apache Iggy server. See [Operations: Apache Iggy](operations.md#apache-iggy).
2. Set `IGGY_URL` on every service. The Helm value is `externalIggy.url`.
3. Run the Iggy connectors runtime and set `IMBI_IGGY_CONNECTORS_API_KEYS`
   on imbi-api. On Kubernetes, set `iggyConnect.enabled`. Without the
   runtime, gateway events do not get to ClickHouse. See
   [Kubernetes: The connectors runtime](kubernetes.md#the-connectors-runtime)
   or [Docker: The Iggy connectors runtime](docker.md#the-iggy-connectors-runtime).

After you deploy, run `setup-permissions`. It adds the five `ai_model:*`
permissions.

## 2.31.0

The gateway uses `publish_release` as a service account with no user. From
2.31.0, a service account must have `integration:act-as-service` to use the
credential of an integration. Without it, `publish_release` gets
`403 service_credential_forbidden`.

1. Run `setup-permissions`. It adds `integration:act-as-service`.
2. Give the permission to the `imbi-gateway` service account. You cannot
   change a built-in role, so create a custom role that has the permissions
   of `imbi-gateway` and `integration:act-as-service`. See
   [Roles and Permissions](../admin/roles-and-permissions.md#create-a-custom-role).
3. Give the service account that role in each organization that owns the
   projects it deploys.

A service account API key with an explicit `scopes` list keeps its scopes.
Issue a new key if the scopes do not include the permission. Imbi caches
API key authentication for 60 seconds, so a grant can take one minute to
apply.

To let autonomous deployments into an environment, turn on
`allow_autonomous` on that environment. It is off by default.

## 2.28.0

After you deploy, run **Repair Deployments Mislabelled Rolled Back**
(`deployment-status-repair`) from **Admin > Global Admin > Maintenance**.
It restores the `success` status that an earlier release overwrote on
deployment nodes.

## 2.26.2

Run `setup-clickhouse`. It adds the `commit_drift` table.

## 2.26.0

Run `setup-permissions` and `setup-clickhouse`.

- `setup-permissions` adds `component:read` and `component:write`.
- `setup-clickhouse` adds the `release_component_batches`,
  `release_components`, and `maintenance_log` tables.

## 2.25.0

No setup commands.

- A direct API call that promotes or cuts a release from a commit with a
  `fail` CI status now gets `409`. Send `acknowledge_ci_failure` on the
  request to continue.
- Examine the rule order of each webhook that you edited in the admin UI
  before 2.25.0. `create_release` must come before
  `add_deployment_event`, and `publish_release` must come after both.
- On the `add_deployment_event` rule, set
  `"external_run_url_selector": "/payload/deployment_status/log_url"` and
  `"external_run_id_selector": "/payload/deployment/id"`.
- The `mainline_branches` option of an integration replaces the default
  branches (`main`, `master`). List every mainline branch.

## 2.24.0

No setup commands. If you set the `artifact_workflow` capability option on
a project, connect the `deployment_status` webhook to the
`publish_release` and `block_release` actions. Without them, a promoted tag
does not become a release.

## 2.23.0

- Run `setup-clickhouse`. In 2.22.0, the `scheduler_runs` table failed to
  create on some ClickHouse versions. 2.23.0 corrects the DDL.
- Set `IMBI_INTERNAL_SCHEDULER_URL` on imbi-api to the in-cluster URL of
  imbi-scheduler, for example `http://imbi-scheduler:8005`. Without it, the
  **System health** card shows the scheduler as not configured.

## 2.22.0

This release adds imbi-scheduler.

1. Run `setup-permissions`. It adds the `scheduled_task:*`,
   `scheduler:impersonate`, and document analytics permissions. It also
   writes all the grants of the built-in roles. Before 2.22.0, the built-in
   roles got only one grant.
2. Run `setup-service-accounts`. It adds the `imbi-scheduler` and
   `imbi-gateway` service accounts. In `all` mode the container does this
   step at startup.
3. Run `setup-clickhouse`. It adds the `scheduler_runs`,
   `document_read_events`, and `document_read_sessions` tables.
4. Run **Reindex Search** (`search-reindex`) one time from
   **Admin > Global Admin > Maintenance**.

## 2.20.0

After you deploy, run **Backfill Deployments to Operations Log**
(`opslog-backfill`) one time from **Admin > Global Admin > Maintenance**.
For the best result, run **Sync Deployments** and **Sync Commits & Tags**
first.
