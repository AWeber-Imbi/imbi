# Pull requests and dependencies

This page tells you how to find pull requests, commits, project
dependencies, and the packages that your projects use.

## Pull requests

Imbi keeps a copy of the pull requests of each project in ClickHouse. The
GitHub plugin keeps the copy current from webhook deliveries. See
[GitHub](../plugins/github.md).

### The Pull Requests tab

Open a project, then click the **Pull Requests** tab. The tab shows only
when a lifecycle plugin is configured for the project. When the project
has open pull requests, the tab label shows the count, for example
**Pull Requests (3)**.

The toolbar has these controls:

| Control | What it does |
|---|---|
| State buttons | **All**, **Open**, **Draft**, **Merged**, and **Closed**, each with its count. **Open** does not include drafts. **Closed** does not include merged pull requests |
| **Mine** | Shows only the pull requests that you opened |
| **Filter by title, author, or #** | Filters by text in the title, the author login, or the pull request number |
| Refresh | Reads the pull requests again |

The table has the columns **#**, **Title**, **State**, **Author**,
**Files**, **Diff**, and **Updated**. Click a title to open the pull request
at the provider. The newest change is first.

The tab reads a maximum of 100 open and 100 closed pull requests.

**Mine** shows only when Imbi knows your GitHub login. Imbi gets it from
your GitHub connection. To connect, see
[Connections](settings.md#connections).

The tab keeps the filters in the URL, so you can share a filtered view:

| Parameter | Values | Example |
|---|---|---|
| `state` | `open`, `draft`, `merged`, `closed`. No parameter is **All** | `?state=open` |
| `author` | `me` | `?state=open&author=me` |
| `q` | Filter text | `?q=renovate` |

The pull request badges on the **Projects** page use these links. The
first badge counts the open pull requests of the project. The second
badge counts your open pull requests. A badge with a count of zero does
not show.

The tab needs the `project:read` permission. The API is
`GET /organizations/{org}/projects/{project_id}/pull-requests/`, with the
`state` (`open` or `closed`), `author`, `limit`, and `offset` parameters.

### Load the pull request history

Webhooks bring only new changes. To load the full history of a project,
for example after you add a project:

1. Open the project.
2. Open the **Doctor** tab.
3. Click **Sync PRs**.

Imbi runs the sync in the background with the service credential of the
integration. The button shows **Syncing...** while the sync runs.

The button shows when you have `project:pull-requests:write`. The
seeded `admin` and `developer` roles have it. See [Doctor](doctor.md).

### Pull requests on the dashboard

| Widget | What it shows |
|---|---|
| **Total Open PRs** | The open pull requests of all projects in the organization, and the number of projects. Click it to open the **Projects** list filtered to projects with open pull requests |
| **My Open PRs** | Your open pull requests |
| **My Pull Requests** | Your recent pull requests, with the **Open**, **Merged**, and **Closed** filters |
| **My PRs to Deploy** | Your merged pull requests that are not yet deployed to a terminal environment |
| **Agent PRs to Deploy** | Merged pull requests from agents and bots that are not yet deployed to a terminal environment |

The "My" widgets need a GitHub connection. Without one, they ask you to
connect GitHub.

A terminal environment is the last environment of a promotion pipeline,
usually production. A merged pull request is "to deploy" when the last
deployment of its project to a terminal environment started before the
merge. These rules also apply:

- Only pull requests merged in the last 90 days count.
- A project that never deployed to a terminal environment does not show,
  for example a library.
- A bot is an author whose login ends in `[bot]`, for example
  `dependabot[bot]`.
- Each row shows how long the pull request waited, for example
  **Waiting 3 days** or **Merged today**.

### Pull request reports

Open **Reports** in the top bar.

**Open Pull Requests** shows the open pull requests of the organization.
It reads a maximum of 500.

- Filter with **All teams**, **All types** (project type), and
  **Filter by title, author, project, or #**.
- The columns are **#**, **Title**, **Project**, **Team**, **Project
  Type**, **Author**, **Files**, **Diff**, and **Updated**.

**PR Activity** shows, for each pull request author, how many pull
requests were **Created**, **Open**, **Closed**, and **Merged** since a
date.

1. Set **Since (inclusive)**. The default is 30 days ago.
2. Click **Fetch activity**.
3. Optional: click **Download CSV**.

Imbi shows the Imbi user of an author when the user connected the GitHub
account. The API is `GET /organizations/{org}/pull-requests/activity`.

## Commits

Imbi also keeps a copy of the commits and tags of the default branch of a
project. The **Releases** or **Deployments** tab uses it. See
[Releases and deployments](releases-and-deployments.md).

A commit row can show a CI status icon. Hold the pointer on the icon to
read its meaning:

| Icon | Meaning |
|---|---|
| Check mark | **CI passed** |
| Warning triangle | **CI passed with warnings** |
| X | **CI failed** |
| Dashed circle | **CI status unknown** |
| Minus | **No CI status — this project has no environments** |

To load the full commit and tag history of a project, open the **Doctor**
tab and click **Sync Commits & Tags**. The button needs
`project:commits:write`.

## Project dependencies

A project can depend on other projects in the same organization. Imbi
stores each dependency as a `DEPENDS_ON` relationship from the project to
the other project.

### See the dependencies

Open a project, then click the **Relationships** tab. The tab label shows
the total, for example **Relationships (4)**.

- **Uses** lists the projects that this project depends on.
- **Used by** lists the projects that depend on this project.
- Use **All**, **Uses**, or **Used by** to filter the list.
- A graph shows the project and its relationships. An orange edge is
  "depends on". A blue edge is "depended upon".

To see the relationships of all projects, open **Reports > Projects
Graph**.

### Change the dependencies

1. On the **Relationships** tab, click **Edit**.
2. In the **Edit Relationships** dialog, find a project with **Search
   projects...**.
3. Select each project that this project depends on. Clear each project
   that it no longer depends on. A changed row is highlighted.
4. Click **Save \<n\> changes**.

A project cannot depend on itself. A change needs `project:write`. The
`admin` and `developer` roles have it.

When the dependencies change, Imbi tells the lifecycle plugins of the
project. For example, the PagerDuty plugin then updates the service
dependencies in PagerDuty. See [PagerDuty](../plugins/pagerduty.md).

A condition scoring policy can test the projects that a project depends
on. See [Scoring policies](../admin/scoring-policies.md).

## Packages and SBOMs

Imbi records the packages (components) that each release of a project
uses. The source is a CycloneDX software bill of materials (SBOM).

### Send an SBOM

Imbi accepts CycloneDX 1.7 only. An SBOM with another `specVersion` is
refused with `415`.

There are two ways to send an SBOM:

- From the build, through the gateway. A webhook rule with the
  `ingest_sbom` action finds the release by its tag and sends the SBOM to
  the API. The action can also create the release when it does not exist.
  See [Gateway](../gateway/index.md) and
  [Webhooks](../admin/webhooks.md).
- Directly to the API. Send the CycloneDX document, with no envelope, to
  `PUT /organizations/{org}/projects/{project_id}/releases/{release_id}/sbom`.
  This needs `project:write`.

A new SBOM for a release replaces the package list of that release.

### The Dependencies tab

Open a project, then click the **Dependencies** tab.

1. Select a tagged release in **Release**. The default is the newest
   release.
2. Read the table.

| Column | What it shows |
|---|---|
| Component | The package name and its package URL name |
| Ecosystem | The package type, for example `npm` or `pypi` |
| Version | The package version |
| License | The license from the SBOM |
| Usage | The CycloneDX scope (`required`, `optional`, `excluded`) and groups |
| Identifiers | Other identifiers from the SBOM, for example a CPE |

When the project has no tagged release, the tab says so. When the release
has no SBOM, the table shows **No SBoM has been ingested for this release
yet.**

### Package governance

You can mark a package, or one version of it, so that every team sees the
mark. The marks are:

| Status | Meaning |
|---|---|
| **Deprecated** | Move off this package or version |
| **Forbidden** | Do not use this package or version |

An unmarked package has no status. The menu shows **Set status**.

You can also record these on a package version:

- An advisory: an **Identifier** (for example `CVE-2025-1234`), a **URL**,
  and an optional **Title**. The same identifier on another version links
  to the same advisory. Imbi does not collect a severity.
- A note. Every team can see the notes. A note cannot be changed or
  removed.

To set a mark, an advisory, or a note:

1. Open **Reports > Package Usage**.
2. Type the package name and press **Enter**.
3. Select the package.
4. Use **Mark this package**, or **Mark this version** on a version row.
   Use the advisory and notes buttons on the version row.

Reading the marks and the package reports needs `component:read`. The
`admin`, `developer`, `default`, and `readonly` roles have it. Setting a
mark, an advisory, or a note needs `component:write`. Only the `admin`
role has it.

### Package reports

**Package Usage** shows every project and environment that runs one
package, grouped by version.

- Search for a package by name. The page keeps your 8 most recently viewed
  packages in your browser.
- Filter with **Package type**, **Project type**, **Team**, and
  **Environment**.
- The header shows **Projects**, **Versions**, **Vulnerable projects**, and
  **Newest deployed**.
- Only releases with an SBOM show.

**Problem Packages** shows the projects that run a version that is
**Forbidden**, **Deprecated**, or has a **Known advisory**.

- The header shows **Projects affected**, **Forbidden versions**,
  **Deprecated versions**, and **Known advisories**.
- Filter by finding, team, project type, package type, and environment.
  Click **Reset** to clear the filters.
- Click **CSV** to download the rows.
- When nothing matches, the report says **Nothing deployed is deprecated,
  forbidden, or carrying a known advisory.**
