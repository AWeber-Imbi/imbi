# Doctor

The Doctor checks that a project is set up correctly in Imbi and in the
systems that Imbi connects to. It shows each result as a finding. Many
findings have a fix that you can apply with one click.

To open the Doctor, open a project and click the stethoscope icon at the
right end of the tab bar. Its tooltip is **Project Doctor**. The icon
color shows the overall result of the last analysis:

| Color | Overall result |
|---|---|
| Red | At least one finding is **Fail** |
| Amber | At least one finding is **Warn**, and none is **Fail** |
| Green | All findings are **Pass**, or there are no findings |
| Gray | No analysis has run yet |

## Run an analysis

1. Open the **Doctor** tab.
2. Click **Analyze** in the **Utility Functions** card.

When you open the tab and no analysis exists, and you have
`project:write`, the analysis starts automatically.

Imbi stores one report for each project. Each analysis replaces the
previous report. Imbi keeps no history of reports. No schedule runs the
analysis for one project. An administrator can run it for all projects
(see [Maintenance operations](#maintenance-operations)).

An analysis runs these checks:

1. The built-in blueprint compliance check.
2. The analysis checks of each plugin that the project uses, at the same
   time. Each plugin has a time limit (10 seconds by default,
   `IMBI_PLUGIN_TIMEOUT_SECONDS`).

If a plugin fails, the report shows one **Fail** finding, "\<plugin\>
analysis failed". The server log has the details.

## Read the results

The **Analysis Results** card shows the findings in three groups, in this
order: **Fail**, **Warn**, and **Pass**. Each group shows its count.
Findings are sorted by title in each group.

Each finding shows:

- a status icon and the title,
- the status (**Fail**, **Warn**, or **Pass**),
- the slug of the plugin that made the finding (`blueprint-compliance` for
  the built-in check),
- when you expand it, a description and, if the finding has one, a fix
  button.

**Fail** and **Warn** findings are expanded. **Pass** findings are
collapsed.

There is no other severity. A finding is a **Fail**, a **Warn**, or a
**Pass**.

| Message | Meaning |
|---|---|
| No analysis has been run yet for this project. | No report exists. Click **Analyze** |
| No analysis plugins reported findings for this project. | The analysis ran, and no check made a finding |
| Failed to load analysis report. | The API returned an error |

## Fix a finding

A finding with a fix shows a button under its description. The text of
the button tells you what the fix does, for example **Create the EXISTS_IN
edge from GitHub**.

1. Expand the finding.
2. Click the fix button.
3. If a dialog opens, read it, then click the button again to confirm.

A dialog opens only for a destructive fix: a fix that creates or deletes
something, or removes a value. When the plugin gives no text for the
dialog, it says "This action cannot be undone."

After the fix, Imbi runs the analysis again and shows the new report. A
message tells you the result: fixed, nothing to do, or failed.

To apply all fixes in the report, click **Fix all** in the **Utility
Functions** card. This applies every fix, destructive ones included,
without a dialog. One failed fix does not stop the others. The message
shows how many were fixed and how many failed.

While one fix runs, all other fix buttons are disabled.

## Utility functions

The **Utility Functions** card has the buttons that you have permission to
use.

| Button | What it does | Permission |
|---|---|---|
| **Analyze** | Runs the analysis | `project:write` |
| **Recompute Score** | Queues a new score for the project. See [Scoring](operations-log-and-scoring.md#scoring) | `scoring_policy:rescore` |
| **Sync Deployments** (or **Sync Releases**) | Reads the recent deployments (or releases) from the deployment plugin again | `project:deployment:write` |
| **Sync Commits & Tags** | Reads commits, tags, and drift notes again. See [Drift](drift.md) | `project:commits:write` |
| **Sync PRs** | Reads pull requests again | `project:pull-requests:write` |
| **Fix all** | Applies every fix in the report. Shows only when a finding has a fix | `project:write` |

The button reads **Sync Releases** for a project whose project types are
releasable and none is deployable.

| Role | What you can do on the Doctor tab |
|---|---|
| `admin` | Everything |
| `developer` | Everything |
| `default` | See the results and recompute the score |
| `readonly` | See the results |

The seeded roles give `project:deployment:write`, `project:commits:write`,
and `project:pull-requests:write` to `admin` and `developer`. The three
sync buttons use only your role in the organization of the project. A
platform administrator who is not a member of that organization gets
`403`. See [Roles and permissions](../admin/roles-and-permissions.md).

## What the Doctor checks

### Blueprint compliance (built-in)

This check runs for every project. It compares the project attributes with
the Project blueprints that apply to the project types. See
[Blueprints](../admin/blueprints.md).

| Finding | Status | Fix |
|---|---|---|
| Required property not set | Fail | **Set \<property\> to its blueprint default**, when the blueprint has a default |
| Property value not in allowed set | Fail | None |
| Property below minimum | Warn | None |
| Property above maximum | Warn | None |
| Property not set — default available | Warn | Sets the default |
| Property not in any applicable blueprint | Warn | **Remove \<property\>** (destructive) |
| All blueprint properties are correctly set | Pass | — |
| No Project blueprints configured | Pass | — |
| No blueprints apply to this project type | Pass | — |

### GitHub

The GitHub plugin checks that the project is linked to the correct
repository. The fixes are not destructive. See [GitHub](../plugins/github.md).

| Check | What it checks | Fix |
|---|---|---|
| GitHub connection | A GitHub host is configured | None |
| Service binding | The project has a GitHub integration | None |
| EXISTS_IN edge | The project is linked to a repository | **Create the EXISTS_IN edge from GitHub** |
| Canonical URL | The stored repository URL exists and the credential can read it | None |
| Identifier type, Identifier match | The stored repository identifier is correct | **Repair the EXISTS_IN edge from GitHub** |
| Identifier verified | The link is verified. GitHub App tokens are not issued until it is | **Verify the EXISTS_IN edge from GitHub** |
| Canonical URL shape | The stored URL has the correct form | **Repair the EXISTS_IN edge from GitHub** |
| Dashboard URL match | The dashboard link points at the repository | **Set the dashboard link from GitHub** |
| github-repository link match | The `github-repository` project link points at the repository | **Set the github-repository link from GitHub** |
| Homepage URL match | The repository homepage on GitHub is the Imbi page of the project | **Set the repository homepage to the project's Imbi page**. This fix changes the repository on GitHub |

When Imbi cannot read the repository, the checks that need it show **Warn**.

### SonarQube

The SonarQube plugin checks the link to the SonarQube project and its main
branch. See [SonarQube](../plugins/sonarqube.md).

| Check | What it checks | Fix |
|---|---|---|
| Project binding, SonarQube URL, SonarQube API token | The integration is set up | None |
| EXISTS_IN edge | The project is linked to a SonarQube project | **Repair the SonarQube project link** when the component exists. **Create / link the SonarQube project** (destructive) when it does not |
| SonarQube project | The linked component exists | **Create / link the SonarQube project** (destructive) |
| Main branch | SonarQube tracks the expected main branch (the `main_branch` option, `main` by default) | **Track '\<branch\>' as the main branch** (destructive). A Fail with no fix when SonarQube has no such branch |
| Canonical URL, Dashboard link | The stored URL and the dashboard link are correct | **Repair the SonarQube project link** |

### PagerDuty

The PagerDuty plugin checks the PagerDuty service of the project, its
escalation policy, and its dependencies. See
[PagerDuty](../plugins/pagerduty.md).

| Check | What it checks | Fix |
|---|---|---|
| Service binding | The project has a PagerDuty integration | None |
| Escalation policy | The team of the project is mapped to an escalation policy | None |
| EXISTS_IN edge | The project is linked to a PagerDuty service | **Repair the PagerDuty service link** when a service with the project name exists. **Create / link the PagerDuty service** (destructive) when none exists. None when the team has no mapped policy |
| PagerDuty service | The linked service exists | **Create / link the PagerDuty service** (destructive) |
| Canonical URL, Dashboard link | The stored URL and the dashboard link are correct | **Repair the PagerDuty service link** |
| Service escalation policy | The service uses the escalation policy mapped to the team | **Repoint the escalation policy** (sync fix) |
| Service dependencies | The service dependencies in PagerDuty match the dependencies of the project in Imbi | **Sync PagerDuty service dependencies** (sync fix). It adds and removes dependencies |

A dependency on a project that has no PagerDuty service is not synced. The
check then shows **Warn**.

### Other plugins

The AWS, Google, Logz.io, and OIDC plugins have no Doctor checks.

## Sync fixes

A plugin can mark a fix as a sync fix. A sync fix only makes a remote
system agree with Imbi. It never creates or deletes a remote resource, and
it is safe to apply again. Today, the two PagerDuty fixes **Repoint the
escalation policy** and **Sync PagerDuty service dependencies** are the
only sync fixes.

### Apply Sync Fixes

**Apply Sync Fixes** is a maintenance operation. It applies the sync fixes
for every project, with no person at the screen.

1. Open **Admin > Global Admin > Maintenance**.
2. Find **Apply Sync Fixes** and click **Run**.
3. Read the dialog. The operation runs for all organizations. Click
   **Run**.

For each project that is not archived, the operation runs a new analysis,
stores the report, and applies only the sync fixes. A project with no sync
fix is skipped with the message "No sweepable findings." The operation
runs as the system principal **Imbi Maintenance**.

You need `admin:maintenance:manage` to run it, and
`admin:maintenance:read` to see it. The seeded roles give these only to
`admin`. See [Maintenance](../admin/maintenance.md).

## Maintenance operations

**Admin > Global Admin > Maintenance** has two more Doctor operations. Each one runs for
every project that is not archived.

| Operation | What it does |
|---|---|
| **Run Analysis** | Runs the analysis and stores the report |
| **Remediate Findings** | Applies every fix in the stored report, destructive fixes included. Skips a project with no report |
| **Apply Sync Fixes** | Runs the analysis, then applies only the sync fixes |

## Scoring

A scoring policy of the category **Analysis Result** can give points for
the status of one Doctor finding. See
[Scoring](operations-log-and-scoring.md#scoring).
