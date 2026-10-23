# Projects

A project is one thing that your teams build and run: a service, a
library, a site, or a job. Each project belongs to one team and has one or
more project types. Imbi collects the facts, links, environments,
deployments, and dependencies of each project in one place.

Projects belong to the organization that you select in the top bar.

## Permissions

| Permission | Lets you | Seeded roles that have it |
|---|---|---|
| `project:read` | See projects | `admin`, `developer`, `default`, `readonly` |
| `project:create` | Create projects | `admin`, `developer` |
| `project:write` | Edit, archive, and restore projects, and change their dependencies | `admin`, `developer` |
| `project:delete` | Delete projects | `admin` |

The UI shows the edit controls to all users. The API refuses a change that
you do not have the permission for. See
[Roles and permissions](../admin/roles-and-permissions.md).

## The projects list

Open **Projects** in the top bar (`/projects`).

### Find a project

- **Search projects...**: type part of the name, the description, the
  team, or the project type. Press `/` to go to the search field. When you
  search, the list is in order of the best match.
- **Toggle chips** above the list. Each chip shows a count for the whole
  organization. Click a chip to show only those projects:

    | Chip | Shows |
    |---|---|
    | **Drifted** | Projects with drift. See [Drift](drift.md) |
    | **Open PRs** | Projects with open pull requests |
    | **My PRs** | Projects with open pull requests that you wrote |
    | **My Teams** | Projects of your teams |

- **Column filters**: open the filter on a column header. Each option shows
  how many projects match it.

    | Column | Filters |
    |---|---|
    | **Project** | **Team** and **Type** |
    | **Drift** | The environment pairs and `C → R`. See [Drift](drift.md) |
    | **Score** | Healthy, Fair, At risk, Unhealthy, Unscored. See [Scoring](operations-log-and-scoring.md#scoring) |

The URL keeps the search, the filters, the sort, and the view. Copy the URL
to share the list as you see it.

### Columns

| Column | What it shows |
|---|---|
| **Project** | The name, the team, and the type. Click to sort by name |
| **PRs** | Open pull requests. See [PR badges](#pr-badges). Click to sort |
| **Drift** | One `Δ` badge for each kind of drift |
| **Current Deployments & Releases** | For a deployable project: the version in each environment. For a release-only project: **Latest Commit** and **Current Release** |
| **Score** | The project score, or **—** when it has no score. Click to sort |

Click a sortable header one time to sort up, and again to sort down.

An environment cell shows the tag or the commit, or **Not deployed**. When a
newer deployment did not finish, the cell shows a pill: **deploying**,
**queued**, **failed**, or **rolled back**.

### PR badges

The **PRs** column shows up to two badges:

- The number of open pull requests. Click it to open the **Pull
  Requests** tab with the open pull requests.
- The number of your open pull requests. Click it to open the same tab with
  only your pull requests.

See [Pull requests and dependencies](pull-requests-and-dependencies.md).

### Drift badges

- `Δ T → S`: two adjacent environments run different code. Click it to go
  to the **Deployments** tab, with the target environment selected.
- `Δ C → R`: the project has commits after its latest release. Click it to
  go to the tab where you cut a release.

See [Drift](drift.md) for the rules.

### Views and loading

- Click **List view** or **Grid view**. Imbi remembers your choice in this
  browser.
- Click **Refresh** to load the list again.
- Imbi loads the list in pages of 50 and loads all pages one after the
  other. The list grows while it loads. If a page fails, the list stops.
  Click **Refresh**.

The list never shows archived projects.

## Create a project

1. Open **Projects**.
2. Click **New Project**.
3. Complete the **Create New Project** dialog:

    | Field | What to enter |
    |---|---|
    | **Team** | Required. The team that owns the project |
    | **Project Type** | Required. One type. You can add more types later |
    | **Name** | Required. The name that people see, for example `My Service` |
    | **Slug** | Required. Imbi makes it from the name until you change it: lowercase, with `-` in place of spaces |
    | **Description** | The purpose of the project |
    | **Environments** | Optional. Click each environment that the project runs in |
    | Blueprint fields | Required. The required fields that have no default, from the `Project` blueprints that match the project type and environments. They show after you select a project type |

4. Click **Save**.

Imbi opens the new project. Imbi then tells the lifecycle plugins about it.
For example, the GitHub plugin can make the repository.

To set the URL or other fields of an environment, edit it on the
**Overview** tab after you create the project. See
[Environments](#environments).

## The project page

### Header

The header shows the name, the description, and the links of the project.
You can edit the name and the description in place. Click **Copy project
ID** to copy the ID. An archived project shows the **Archived** badge.

The link bar shows the project links and the dashboards of its
integrations, in alphabetical order.

### Tabs

Some tabs show only when the project has the plugin or the project type
that the tab needs.

| Tab | Shows when | What it shows |
|---|---|---|
| **Overview** | Always | Details, attributes, environments, health score, and recent activity |
| **Configuration** | The project has a configuration plugin | Configuration values from the plugin |
| **Dependencies** | Always | The packages of the project. See [Pull requests and dependencies](pull-requests-and-dependencies.md) |
| **Deployments** | The project is deployable (see [Delivery](#delivery)), has a deployment plugin, and at least one environment | Environments, promotion, and history. See [Releases and deployments](releases-and-deployments.md) |
| **Releases** | The project is releasable (see [Delivery](#delivery)) and has a deployment plugin | Releases. See [Releases and deployments](releases-and-deployments.md) |
| **Documents (N)** | Always | Project documents. See [Documents and reports](documents-and-reports.md) |
| **Incidents** | The project has an incidents plugin | Incidents, for example from PagerDuty |
| **Logs** | The project has a logs plugin | Logs, for example from Logz.io |
| **Operations Log** | Always | The operations log of this project. See [Operations log](operations-log-and-scoring.md#operations-log) |
| **Pull Requests (N)** | The project has a lifecycle plugin | Pull requests. N is the number of open ones |
| **Relationships (N)** | Always | Dependencies between projects. See [Relationships](#relationships) |
| **Score History** | Always | See [Score History](operations-log-and-scoring.md#score-history-tab) |
| Stethoscope icon | Always | The [Doctor](doctor.md) |
| Gear icon | Always | **Project Settings** |

The refresh icon next to the tabs loads the project data again.

### Overview tab

| Card | What it shows |
|---|---|
| **Project details** | **Team**, **Slug**, **Project Types**, **Created**, and the attributes. Click a value to edit it |
| **Environments** | The environments of the project, with a URL and the deployment status of each |
| **Health & compliance** | The **Health score**, its change, and **Score breakdown**. See [Scoring](operations-log-and-scoring.md#scoring) |
| **Recent activity** | Recent changes to the project |

## Edit a project

Click a value to edit it. Imbi saves each change at once. You need
`project:write`.

### Attributes

Attributes are the facts about a project, for example its language or its
tier. The [blueprints](../admin/blueprints.md) of the project types define
which attributes exist, their types, and their allowed values. The editor
matches the type:

| Attribute type | Editor |
|---|---|
| Allowed values (enum) | A list |
| List (array) | A list editor |
| True or false | A switch |
| Date | A date picker |
| Number | A number field |
| Text | A text field |

An attribute with no value shows **Not set**. Hover over the label to see
its description. You cannot edit `id`, `created_at`, `updated_at`, or an
attribute that its blueprint marks as not editable.

The [Doctor](doctor.md) tells you when an attribute does not follow its
blueprint.

### Change the project type

When you change the project types and the project has a lifecycle plugin,
Imbi first asks the plugin if the repository must move. The dialog **Move
the backing repository?** lists each change. The type change is saved in
all cases. Select **Also move the repository to the new location.** only
when you also want the plugin to move the repository. It is not selected
by default.

### Links

Links are on the **Project Settings** tab (the gear icon).

1. Open **Pick Link Type to Add** and select a link type. An administrator
   defines the link types. See
   [Catalog settings](../admin/catalog-settings.md).
2. Enter the URL.
3. To remove a link, click its remove button and confirm.

Links that an integration owns do not show here. The integration sets them.

### Environments

1. On the **Overview** tab, find the **Environments** card.
2. Click **Add environment**. The button shows only when an environment is
   not on the project yet.
3. Select the **Environment**. Optional: enter its **URL** and the other
   fields that the blueprint of the environment defines.
4. Click **Add**.

To remove an environment, click its remove button and confirm.

### Delivery

**Releases and deployments** in the project settings says how Imbi ships
the project. The default, **By project type**, follows the `deployable`
or `releasable` flag of the project types: a deployable type gives the
project the **Deployments** tab, otherwise a releasable type gives it the
**Releases** tab. The other options override the project types for this
one project:

| Option | What it does |
|---|---|
| **By project type** | Follow the flags of the project types (default) |
| **Deployable** | Deploy into environments and promote between them, whatever the types say |
| **Releasable** | Cut tags and releases with no deploy step, whatever the types say |
| **Disabled** | Turn release and deployment processing off. Neither tab shows, and the API refuses to deploy, promote, resync, draft release notes, or cut a release for the project |

Use **Disabled** for a project whose releases are governed outside Imbi,
for example a plugin with its own release process.

### Archive and restore

1. Open the **Project Settings** tab (the gear icon).
2. Click **Archive project**, then click **Archive project** in the dialog.
   Imbi hides the project from the dashboard, the projects list, and the
   search results. Imbi keeps its data.

To restore the project, open it by its URL and click **Restore project**
on the same tab.

### Delete

1. Open the **Project Settings** tab.
2. Click **Delete Project**.
3. Type the slug of the project.
4. If the project has a lifecycle plugin, the box "Also delete the
   associated repository" is selected. Clear it to keep the repository.
5. Click **Confirm Delete**.

The delete removes the project and its facts, operations log entries, and
documents. You cannot undo it. You need `project:delete`.

## Relationships

A relationship says that one project depends on another project. The
**Relationships** tab shows them in two directions:

- **Uses**: the projects that this project depends on.
- **Used by**: the projects that depend on this project.

Use the **All**, **Uses**, and **Used by** chips to filter the list. The
graph shows the project in the center. Use the layout list, the zoom
buttons, **Fit to view**, and **Fullscreen** to move around. Double-click a
project to open it.

### Change the dependencies

1. Open the **Relationships** tab.
2. Click **Edit**.
3. Select each project that this project depends on. Use **Search
   projects...** to find a project.
4. Click **Save**. The button shows the number of changes.

You can edit only the **Uses** direction of this project. A project cannot
depend on itself. A change can change the score when a scoring policy reads
dependencies.

To see the dependencies of all projects, open **Reports > Projects Graph**.

## Integrations and plugins

The **Project Settings** tab also shows the integrations of the project
and its plugins. A project with a lifecycle plugin has a **Sync Lifecycle**
button. It sends the current state of the project to each lifecycle
plugin again, for example to create or update the PagerDuty service. See
[Integrations and plugins](../admin/integrations-and-plugins.md).
