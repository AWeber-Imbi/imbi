# Documents, reports, and the dashboard

## Documents

A document is a Markdown page in Imbi, for example a runbook, a design
decision, or a review. Each document is attached to one of these:

| Attachment | Where you make it | Who it is for |
|---|---|---|
| A project | The **Documents** tab of the project | The project |
| A project type | **Documents** in the top bar | All projects of that type |
| A user | **Documents** in the top bar ("Personal") | You |

**Documents** in the top bar (`/documents`) lists the documents of the
selected organization.

- **Activity feed** shows the documents, newest change first.
- **Index** shows a table with the columns **Document**, **Attached to**,
  **Author**, **Tags**, and **Updated**.
- **Search all documents…** filters both views.

On a project, the **Documents** tab shows the project documents. The tab
label shows the count, for example **Documents (4)**. Use **Search
documents** and the **Tags** filter to find a document. Pinned documents
show first, under **Pinned**.

### Write a document

1. Click **New document**.
2. Select **Blank document**, or select a template. When no template
   applies, the button makes a blank document at once.
3. On the **Documents** page only: select the attachment in **Attach to**.
   The choices are **Personal** and each project type.
4. Enter the **Title**.
5. Optional: add tags.
6. Write the content in Markdown. Use **Write**, **Split**, or **Preview**
   to change the view.
7. Click **Save**. Click **Discard** to leave without a save.

To change a document, open it and click **Edit**.

### Templates

A template gives a new document its title, content, and tags. An
administrator makes templates in **Admin**. See
[Catalog settings](../admin/catalog-settings.md).

The **New document** menu shows only the templates that apply:

- A `project` template applies to project documents. It can be limited to
  some project types.
- A `project_type` template applies to project type documents.
- A `user` template applies to personal documents.
- A `global` template applies everywhere.

On the **Documents** page, the menu shows every template. A
`project_type` template selects its project type in **Attach to** for
you.

### Someone else is editing

When you edit a document, Imbi marks you as an editor of it. Other people
who edit the same document see a notice: "\<name\> is also editing this
document — the last save wins."

The notice is advisory only. Imbi does not lock the document. When two
people save, the second save replaces the first. Each save is in the
history, so you can restore the content that was replaced.

The editor sends a heartbeat to keep the mark. A mark expires 30 seconds
after the last heartbeat.

### History and restore

Each save that changes the title, the content, or the tags makes a new
version. A save that changes only the pin makes no version.

1. Open the document.
2. Click **History**.
3. Select a version. Each version shows its kind (**Created**,
   **Edited**, **Restored**, or **Original**), who saved it, and when.
4. Click **Content** to read the version, or **Changes** to see the
   difference between the version and the current document.
5. Optional: click **Restore v\<n\>**, then **Restore** to confirm.

A restore does not remove history. It saves the old content as a new
version of the kind **Restored**. A tag that no longer exists is dropped.

**Original** is the content of a document that existed before Imbi
recorded versions.

### Pin, like, and comment

- **Pin** puts a project document in the **Pinned** group of the
  **Documents** tab. **Unpin** removes it.
- **Like** adds your like. Click **Liked** to remove it.
- To comment on a part of the text, select the text and use the
  toolbar that shows. Comments that are not on a part of the text show
  under the document. Use **Open** and **Resolved** to filter the
  comments. Use **Hide inline comments** to hide the marks in the text.

### Who read a document

Imbi records how people read each document. Open a document and click the
readers count, for example **4 readers**. The **Readership** popover has
two views:

- **Views** shows the views (all time), the unique readers, and the
  recent readers.
- **Engagement** shows how long people read and how far they scrolled.

Click **View full readership report** to open the report for all
documents.

Imbi counts a read like this:

1. While the document is visible and you use the page, the browser sends
   a heartbeat every 15 seconds.
2. A visit with less than 5 seconds of engaged time is not a view.
3. A view is a read when you scroll to 80% of the document, or when you
   stay for its estimated read time (220 words a minute).
4. A visit ends after 5 minutes with no heartbeat.

These rules also apply:

- The counts show human reads in the web UI only. A fetch by the
  assistant, an MCP client, the Slack bot, or the API is not a read.
- The author's own reads do not count.

The names of the readers are private by default. The organization setting
`document_analytics_identities` controls who sees them:

| Value | Who sees the names of the readers |
|---|---|
| `authors_only` (default) | The author of the document, and holders of `document:analytics:read_identities` |
| `enabled` | Holders of `document:analytics:read_identities` |
| `disabled` | Nobody. The popover shows **Individual readers are not shown for this organization.** |

The UI has no control for this setting. Change it with the organizations
API. You always see your own reading history.

### Document permissions

| Permission | Lets you | Roles that have it |
|---|---|---|
| `document:read` | Read documents and their history. Like a document | `admin`, `developer`, `default`, `readonly` |
| `document:create` | Make documents | `admin`, `developer` |
| `document:write` | Edit, pin, and restore documents | `admin`, `developer` |
| `document:delete` | Delete documents | `admin`, `developer` |
| `document:analytics:read` | See read counts and the readership report | `admin`, `developer`, `default`, `readonly` |
| `document:analytics:read_identities` | See who read a document | `admin` |
| `comment:create`, `comment:write`, `comment:delete` | Add, edit, and delete comments | `admin`, `developer` |

## Reports

Click **Reports** in the top bar. The left side lists the reports. Each
report has its own URL, `/reports/<id>`. `/reports` opens **Monthly
Improvement**.

| Report | URL id | What it shows |
|---|---|---|
| Monthly Improvement | `monthly-improvement` | For each team, the change in score during the month that you select in **Month**, and the stack health score |
| Open Pull Requests | `open-pull-requests` | The open pull requests of the organization. See [Pull requests and dependencies](pull-requests-and-dependencies.md#pull-request-reports) |
| PR Activity | `pr-activity` | Pull requests created, open, closed, and merged for each author, since a date. See [Pull requests and dependencies](pull-requests-and-dependencies.md#pull-request-reports) |
| Package Usage | `package-usage` | Every project and environment that runs one package, by version. See [Package reports](pull-requests-and-dependencies.md#package-reports) |
| Problem Packages | `problem-packages` | Projects that run a deprecated or forbidden version, or one with a known advisory. See [Package reports](pull-requests-and-dependencies.md#package-reports) |
| Projects Graph | `projects-graph` | The dependency relationships between the projects of the organization |
| Score History | `score-history` | The average score of each team over **30d**, **90d**, **1y** (default), or **All**, and the **Change events** list of recent score changes |
| Document Readership | `document-readership` | Documents in the order that you select: **Most read**, **Stale**, **Least read**, or **Never read** |
| Team KPI | `team-kpi` | The average score of each team, with its best project and when it was last scored |

Notes on some reports:

- **Document Readership** shows a maximum of 100 documents. **Stale**
  means read, but not in the last 90 days. **Never read** means that no
  person opened it. The counts follow the rules in
  [Who read a document](#who-read-a-document).
- **Score History** marks each change event with its cause, for example
  **Attribute**, **Blueprint**, **Policy**, **Rescore**, or **System**. For
  scores, see [Operations log and scoring](operations-log-and-scoring.md).
- **Team KPI** and **Score History** show no data until Imbi scores the
  projects.

## Dashboard

The dashboard (`/dashboard`) is the first page after you sign in. `/` and
each unknown URL also open it. Click the Imbi logo in the top bar to go
back to it.

### Widgets

| Widget | What it shows | Shown by default |
|---|---|---|
| **Total Projects** | The number of projects. Click it to open **Projects** | Yes |
| **Active Deployments** | The deployments that have not completed, in the 50 newest deployment entries of the operations log | Yes |
| **Total Open PRs** | The open pull requests of the organization | Yes |
| **My Open PRs** | Your open pull requests | Yes |
| **Recent Deployments** | The latest deployment activity in all environments | Yes |
| **My Pull Requests** | Your recent pull requests | Yes |
| **My PRs to Deploy** | Your merged pull requests that are not deployed to a terminal environment | Yes |
| **Agent PRs to Deploy** | Merged pull requests from agents and bots that are not deployed to a terminal environment | Yes |
| **Recent Activity** | The latest actions and updates in all projects | No |
| **Project Activity** | A short feed of recent activity, by project | No |

For the pull request widgets, see
[Pull requests on the dashboard](pull-requests-and-dependencies.md#pull-requests-on-the-dashboard).
**Active Deployments** reads only 50 entries, so it can show fewer active
deployments than exist.

### Change the dashboard

1. Click **Customize**.
2. In **Customize Dashboard**, click a widget to add it or remove it.
3. Close the dialog.
4. Drag a widget to move it.

Imbi keeps your widgets and their order in your browser only. Another
browser shows the default widgets.

At the top of the dashboard, Imbi shows a card for each identity provider
that you did not connect. See [Connections](settings.md#connections).
