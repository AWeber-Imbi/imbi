# Releases and deployments

Imbi shows what runs in each environment, and lets you release, deploy,
and promote a project from its project page. The deployment plugin of the
project (for example GitHub) does the work. Imbi records the result.

A project gets one of two tabs:

| Tab | Shows for a project that | What you do there |
|---|---|---|
| **Deployments** | Has a deployable project type, a deployment plugin, and at least one environment | Deploy commits, promote between environments, and roll back |
| **Releases** | Has a releasable project type, no deployable type, and a deployment plugin | Cut releases (tags and release notes) |

If you have no connection to the provider of the plugin, the tab asks you
to connect it. Open **Settings > Connections** to connect. See
[Settings](settings.md).

## Permissions

| Permission | Lets you |
|---|---|
| `project:deployment:read` | See the deployment history and the commits on the tab |
| `project:deployment:write` | Deploy, promote, cut releases, draft release notes with AI, and add or resolve blockers |
| `project:commits:write` | Run a commit sync |

The seeded `admin` and `developer` roles have all three permissions. The
`default` and `readonly` roles have `project:deployment:read`.

These routes use only your role in the organization of the project. A
platform administrator who is not a member of that organization gets
`403`. See
[Roles and permissions](../admin/roles-and-permissions.md#permissions-across-organizations).

Only an administrator can delete a blocker. Other people resolve it.

## Environments and pipelines

Environments are in one list, ordered by sort order. An environment with
the **Terminal Environment** flag ends a pipeline. The next environment
starts a new pipeline. Code moves from one environment to the next in its
pipeline. It never moves past a terminal environment.

The **Deployments** tab has two parts:

1. **Pipeline**, on the left: each environment, with the tag or the commit
   that it runs, or `not deployed`. Badges tell you what waits:
    - **Release \<tag\> is waiting to deploy here**
    - **N commits waiting to promote here**
    - **In sync**
2. The selected environment, on the right.

Click an environment to select it. The URL keeps it as `?env=<slug>`.

Each environment is one of three kinds of stage:

| Stage | When | What you do |
|---|---|---|
| Commit | The first environment of a pipeline | Deploy a commit |
| Promote | The environment before it runs a commit with no tag | Cut a tag from that commit and deploy it here |
| Release | The environment before it runs a tag | Deploy that tag here |

## What runs in an environment

The **Currently running** card shows:

- the tag, the commit, and the CI status,
- **Deployed** with the time and, when Imbi knows it, the person who
  deployed,
- the URL of the environment,
- the release notes of the running tag,
- **Recent releases**, with a **Deploy** or **Roll back** button on each.

The **Environments** card on the **Overview** tab also shows the status in
each environment:

| Status | Meaning |
|---|---|
| **Deployed** | The last deployment succeeded |
| **Deploying** | A deployment runs |
| **Queued** | A deployment waits to start |
| **Failed** | The last deployment failed |
| **Rolled back** | The deployment was replaced. GitHub reports this as `inactive` |

### Deployed by

**Deployed by** shows the Imbi name of the person who deployed. When Imbi
has no Imbi user for that person, it shows the login from the provider,
for example the GitHub user who created the deployment. A GitHub webhook
does not name a person, so Imbi uses the person from the operations log
entry of the same deployment. When Imbi knows no person, the card does not
show **Deployed by**.

## Deploy a commit

On a commit stage, the **Recent commits** card shows the 25 newest
commits. Each row shows the drift marker, the commit, **HEAD** for the
newest commit, its tags, the subject, the CI status, the age, and the
author.

1. Select the environment in **Pipeline**.
2. Find the commit. Click **Deploy** (or **Roll back** for an older
   commit).
3. Read the dialog and confirm.

A message shows while the deployment runs, with **View run** to open the CI
run.

If no commits show, run a sync. See [Sync](#sync-commits-tags-and-releases).

## Promote

On a promote stage, the card **Promote from \<upstream\>** shows the commits
that wait.

1. Select the environment in **Pipeline**.
2. Select the newest commit to include. Newer commits stay behind.
3. Check **New tag**. Imbi suggests the next version after the newest tag of
   the project.
4. Check the release notes. Click **Regenerate with AI** to draft them
   again, or **Reset**.
5. Click **Tag \<tag\> & deploy to \<env\>**.

Imbi then does these steps:

1. It refuses the promote if the environment does not allow it, if the
   release is blocked, if the same tag is already in flight, or if the tag
   does not match the tag formats.
2. It checks CI. See [CI gating](#ci-gating).
3. It cuts the tag and asks the plugin to deploy it. If the project type
   has a release workflow, the plugin runs that workflow first to build the
   artifact.
4. When the deployment succeeds, Imbi publishes the GitHub release.

When the upstream environment runs nothing, the card says "deploy upstream
first". When nothing waits, it says **Up to date with \<upstream\>**.

## Deploy a release

On a release stage, the card shows the tags that wait, for example
**Release \<tag\> is waiting to go live**.

1. Select the release.
2. Click **Deploy \<tag\> to \<env\>**.

No new tag is cut. When you select an older release than the one that
runs, the card warns you.

## Cut a release

On the **Releases** tab (for a project that is only released, not
deployed):

1. The card shows **N commits ready to release**. Select the newest commit
   to include.
2. Check **New tag**. The hint shows the suggested bump (major, minor, or
   patch).
3. Check the release notes. Click **Regenerate with AI** or **Reset**.
4. Click **Tag \<tag\> & release**.

If the project type has a release workflow, the workflow creates the tag
and the GitHub release. Otherwise Imbi creates them.

When nothing is new, the card says **Up to date**.

The tab also shows **Currently released** (the latest published release)
and **Release history**.

### Tag formats

A new tag must match a tag format:

1. The tag formats of the project types, when they have some.
2. Else the tag formats of the organization.
3. Else any tag.

The built-in formats are **Semantic versioning**, **Calendar versioning**,
**Git short SHA**, and **Any format**. With no formats set, the UI still
asks for a semver tag, for example `v6.5.2`. The API returns `400` for a tag
that does not match.

### Release notes

You write the release notes in a Markdown editor. Click **Regenerate with
AI** to let the Imbi Assistant draft them from the commits. When the AI is
not available, Imbi groups the commits by their conventional-commit prefix
and shows **(AI unavailable)**.

For a release that Imbi did not cut (for example, one that came from a
webhook or a sync), the GitHub plugin reads the notes from the GitHub
release.

### Release history

Each release shows these badges when they apply:

| Badge | Meaning |
|---|---|
| **Blocked (n)** | The release has n open blockers |
| **Drift** | CI reported drift on the commit of this release. See [Drift](drift.md#release-drift) |
| **CI overridden** | Someone released it over a failing CI run |
| **Latest** | The newest release |

Expand a release to see its notes, **View tag**, and **Add blocker**.

## Blockers

A blocker stops a release. While a release has an open blocker, Imbi
refuses each deploy, promote, and publish of it with `409`. Environments
that already run it keep it.

### Add a blocker

1. Find the release in **Recent releases** (Deployments tab) or **Release
   history** (Releases tab).
2. Click the block button (**Block \<tag\> from being deployed**), or
   **Add blocker**.
3. Select the **Type**: Manual, Product review, QA, Deployment order,
   Dependency, Build failure, or Drift.
4. Enter the reason (required, up to 500 characters).
5. Click **Add blocker**.

A release can have more than one blocker.

Imbi also adds blockers:

| Blocker | Added when |
|---|---|
| Build failure | The release workflow fails |
| Drift | CI reports drift on the commit of the release. A later verdict that is not `true` resolves it |
| Manual (from the gateway) | The `block_release` gateway action receives a failed or errored GitHub deployment. The reason comes from the action configuration, or is "Deployment reported \<state\>" |

### Unblock

- On the **Deployments** tab, a blocked release shows "Blocked from
  deploying and promoting", the reason, and who blocked it. Click
  **Unblock** to resolve all its open blockers.
- In **Release history**, click **Resolve** on one blocker, or **Resolve
  all**.

If you cannot unblock, the card tells you to ask someone with deploy access
on the project.

## CI gating

Before a deploy, a promote, or a release, Imbi reads the CI status of the
commit from the plugin. The CI status dot shows it:

| Dot | CI status | Effect |
|---|---|---|
| **CI passed** | All checks passed | None |
| **CI passed with warnings** | A check was cancelled or stale | None |
| **CI status unknown** | Checks run, there are none, or Imbi cannot read them | None |
| **CI failed** | A check failed, timed out, or needs action | Blocks the action until you acknowledge it |

When CI failed, the dialog shows **CI failed for \<sha\>** and a check box,
for example **Deploy anyway**. Select it to continue. Imbi records the
override, and the release shows **CI overridden**. A service account that
acts with no person cannot acknowledge a CI failure.

## Environment settings

An administrator sets these on each environment. See
[Catalog settings](../admin/catalog-settings.md).

| Setting | Effect |
|---|---|
| **Terminal Environment** | Ends a pipeline |
| **Allow Autonomous Deployments** | Lets a service account with no person deploy to this environment |

The API also has `can_deploy` (default true) and `can_promote` (default
false) on each environment. The API refuses a deploy or a promote that the
flag does not allow. The admin form has no field for them. The tab does not
show them, so a refused action shows as an error.

## Sync commits, tags, and releases

The sync icon next to **Pipeline** (or the **Releases** header) is **Sync
commits, tags & releases**. It does two things:

1. It syncs commits and tags from the plugin. This needs
   `project:commits:write`.
2. It reads the last 100 deployments from the plugin again.

The **Doctor** tab has the same syncs as separate buttons. See
[Doctor](doctor.md#utility-functions).

## How Imbi records a deployment

| Source | What happens |
|---|---|
| You deploy or promote in Imbi | Imbi records the deployment and adds a **Deployed** entry to the operations log. A deploy of a commit that has no release in Imbi is not recorded |
| A GitHub deployment webhook | The gateway records the status for the release. Imbi ignores a second event for the same run |
| A sync | Imbi reads recent deployments from the plugin and records the ones that it does not have |

GitHub sends no webhook when a deployment becomes `inactive`. Imbi sees it
only on a sync, and shows it as **Rolled back**, not as a failure.

## Recent deployments

The **Recent Deployments** card is a widget on the **Dashboard**. It is not
on the project page. It reads the **Deployed** entries of the
[operations log](operations-log-and-scoring.md#operations-log) for the last
30 days, 20 at a time. Click an environment chip to filter.

Each row shows the team and project, the version, the environment, the
status, the person, and the time. Click a row to open the project.

The status comes from the operations log entry, not from the deployment:

| Status | Meaning |
|---|---|
| **In Progress** | The entry is not complete |
| **Success** | The entry is complete |

This has two known problems:

- A deployment that failed also shows **Success**, because a failed
  deployment also completes the entry.
- An entry for a release cut, a release publish, or a deleted blocker has no
  environment and no CI run. It shows **In Progress** with an empty
  environment badge, and never completes.

To see the real status of a deployment, open the **Deployments** tab of the
project.
