# Operations log and scoring

## Operations log

The operations log records what happened to your projects: deployments,
configuration changes, restarts, migrations, and more. Imbi writes most
entries automatically. You can also add an entry by hand.

You can open the log in two places:

- **Operations Log** in the top bar shows the log for all projects of the
  organization (`/operations-log`).
- The **Operations Log** tab of a project shows the log for that project
  only.

Imbi stores the log in the ClickHouse `operations_log` table.

### Permissions

| Permission | Lets you | Seeded roles that have it |
|---|---|---|
| `operations_log:read` | See the log | `admin`, `developer`, `default`, `readonly` |
| `operations_log:create` | Add an entry | `admin` |
| `operations_log:update` | Change an entry (API only) | `admin` |
| `operations_log:delete` | Delete an entry (API only) | `admin` |

See [Roles and permissions](../admin/roles-and-permissions.md).

### Entry types

| Type | Written by |
|---|---|
| Deployed | Imbi, for each deploy, promote, release, and publish. People can also add it |
| Configured | Imbi, when you set or delete a value on the **Configuration** tab. People can also add it |
| Agent Task | Imbi only, when an [agent task](../admin/agent-tasks.md) of a project is resolved or gets an outcome |
| Decommissioned, Migrated, Provisioned, Restarted, Rolled Back, Scaled, Upgraded | People |

You cannot add an **Agent Task** entry by hand.

A **Deployed** entry that Imbi writes has the version (the tag, or the
commit), the environment, and a link to the CI run. While the deployment
runs, the entry is not complete. When the deployment plugin reports the
result, Imbi marks the entry complete. The entry details then show the
**Completed** chip. The Recent Deployments card on the dashboard shows
an entry that is not complete as **In Progress**. See
[Releases and deployments](releases-and-deployments.md#recent-deployments).

### The global page

The page has these parts:

1. **Summary tiles**: **Events**, **Deploys** (with the number to the last
   environment of each pipeline), **Projects touched**, and **Team
   members**, for the selected time range.
2. **The toolbar**:

    | Control | Options |
    |---|---|
    | Time range | **24h**, **7d**, **30d** (default), **90d**, **All** |
    | **Entry Type** | The types in the loaded entries, with counts |
    | **Environment** | The environments in the loaded entries |
    | **Project** | Search and select projects |
    | View | **Releases** (default) or **Stream** |

3. **The entries**, newest first, grouped by day (**Today**, **Yesterday**,
   then the weekday).

You can select more than one value in a filter. Imbi shows an entry that
matches any selected value of a filter, and that matches all filters.
Active filters show as chips. Click **Clear all** to remove them.

The page loads 200 entries at a time. More entries load when you scroll
down. At the end, the page shows "End of log" and the number of entries.

### Stream and Releases views

- **Stream** shows one row for each entry: the type, the project, the
  version, the environment, who did it, and when. The description is on a
  second line.
- **Releases** groups the **Deployed** entries of one version of one
  project into one card. The card shows the environments that the version
  went to, in order. Expand the card to see the **Promotion timeline**:
  each environment, the version, the link, the time, and who did it. A
  deploy with no tag joins the release of the same commit.

### Entry details

Click an entry to see its details:

- the plugin data, for an entry that a plugin wrote,
- **Notes**, when they are different from the description,
- **Link**,
- the chips **Ticket**, **Completed**, **Recorded by** (when it is a
  different person), and **Occurred**,
- **Go to Project** and **Duplicate**.

**Duplicate** opens the **New Ops Log Entry** dialog with the values of
this entry.

To share an entry, copy the URL. The `?entry=<id>` parameter opens and
shows that entry.

### Add an entry

1. Click **+** in the top bar, then **New Ops Log Entry**.
2. Select the **Project**.
3. Select the **Environment**. The list shows only the environments of
   that project.
4. Select the **Entry Type**.
5. Enter the **Description**, a short summary.
6. Optional: enter the **Version**, the **Link**, the **Ticket** (for
   example `INC-1234`), and the **Notes**.
7. Click **Save**.

**Save** is disabled until you complete the four required fields.

Imbi records who added the entry and when. The person who did the work is
the same person, unless the API call sets another.

### Notes and #N links

**Notes** are Markdown. Use the **Write** and **Preview** tabs to check
them.

In notes on a project page, `#123` becomes a link to issue or pull request
123 of the project's GitHub repository. Imbi finds the repository from the
GitHub integration of the project, or from its `github-repository` link.
The preview in the **New Ops Log Entry** dialog also makes these links. On
the global **Operations Log** page, `#123` stays plain text.

The description is plain text. It is not Markdown.

### Change or delete an entry

The UI cannot change or delete an entry. Use the API:

- `PATCH /operations-log/{id}` takes a JSON Patch. You cannot change `id`,
  `project_id`, `occurred_at`, `recorded_at`, or `recorded_by`.
- `DELETE /operations-log/{id}` hides the entry. Imbi keeps a deleted
  marker for it.

## Scoring

Each project has a score from 0 to 100. The score tells you how well the
project follows the rules of your organization. Administrators write those
rules as scoring policies. See
[Scoring policies](../admin/scoring-policies.md).

### Where you see the score

| Place | What it shows |
|---|---|
| Projects list | The **Score** column, and the **health score** filter |
| Project **Overview** tab | The **Health & compliance** card: **Health score**, the change over 30 days, and **Score breakdown** |
| Project **Score History** tab | The score over time, and each change |
| Top-bar search | The score of each project in the results |

The score badge is green at 80 or more, amber at 70 to 79, and red below
70. It shows **—** when the project has no score.

The **health score** filter on the projects list uses other ranges:

| Option | Score |
|---|---|
| Healthy | 85 to 100 |
| Fair | 75 to 84 |
| At risk | 50 to 74 |
| Unhealthy | Less than 50 |
| Unscored | No score |

### How Imbi calculates the score

1. Imbi finds the policies that apply to the project: each enabled policy
   whose project types include a type of the project. A policy with no
   project types applies to all projects. A policy that reads an attribute
   applies only when a blueprint of the project defines that attribute.
2. Each policy gives the project a value from 0 to 100. A value that the
   policy does not map gives 0.
3. The score is the weighted average: the sum of (value × weight), divided
   by the sum of the weights.

When no policy applies, the project has no score.

| Policy category | What it scores |
|---|---|
| Attribute | The value of an attribute, by a value map or by ranges |
| Presence | If an attribute has a value |
| Link Presence | If the project has a link of a link type |
| Age | How old a date attribute is |
| Analysis Result | The status (pass, warn, fail) of one [Doctor](doctor.md) finding |
| Condition | A true or false test on attributes and dependencies |
| Deployment Status | The deployment status in each environment. The API supports it. The policy form cannot create it |

### When the score changes

Imbi calculates the score again when:

- a project is created, or its attributes change,
- its dependencies change,
- a blueprint changes,
- a scoring policy changes,
- a deployment status changes,
- every day at 06:00 UTC, for all projects,
- someone asks for it.

While a calculation for a project is in the queue, more changes to that
project do not add a calculation, so many changes give one calculation.
A change that you save after the calculation starts adds a new one, so
the score always includes your last change.

To ask for a new score for one project, open the **Doctor** tab and click
**Recompute Score**. You need `scoring_policy:rescore`. The `developer` and
`default` roles have it. An administrator can recompute all scores with
**Recompute Scores** in **Admin > \<organization\> Admin > Scoring Policies**. That needs
`scoring_policy:rescore_all`, which only `admin` has.

### Score breakdown

On the **Overview** tab, expand **Score breakdown** in the **Health &
compliance** card. It shows each policy and what it adds to the score. A
policy that is not at its maximum tells you the value that would improve
the score.

### Score History tab

The **Score History** tab shows the current score (**N / 100**) and a
chart of the score over time.

| Control | Options |
|---|---|
| Range | **30d**, **90d**, **1y** (default), **All** |
| Granularity | **Raw**, **Hour**, **Day** (default) |

The chart marks each change with its reason: **Attribute**, **Blueprint**,
**Rescore**, **Policy**, or **System**. Other reasons show by their name.

**Change events** lists each calculation that changed the score, newest
first: the time, the reason, the change, and, for an attribute change, the
old and the new value. Imbi records a history row only when the score
changes.

Use the **All reasons** list to show the events of one reason only. The
chart marks follow the same filter. **Export CSV** downloads the events
that show, with the columns `timestamp`, `reason`, `previous_score`, and
`score`.

The **Reports** page has two reports about scores: **Score History** (the
average score of each team over time) and **Monthly Improvement**.
