# Sentry

The `sentry` plugin connects Imbi to a Sentry organization. It does these
things:

- When you create an Imbi project, it creates a Sentry project with the
  same slug, or links the Sentry project that exists.
- When Sentry sends an issue webhook, it counts the issues of the project
  in Sentry and writes the counts to project facts, for example
  `sentry_open_issues`.
- In the project **Doctor**, it checks the link to the Sentry project and
  the issue-count facts, and offers fixes.

## Capabilities

| Capability | Label | Default | Scope |
|---|---|---|---|
| `lifecycle` | Project lifecycle | On | Project-scoped |
| `webhook-actions` | Webhook actions | On | Project-scoped |
| `analysis` | Project doctor | On | Project-scoped |

## Configuration

### Options

| Option | Label | Required | Meaning |
|---|---|---|---|
| `service_url` | Sentry URL | No | The base URL of Sentry. Blank means `https://sentry.io` |
| `organization` | Sentry organization slug | Yes | The Sentry organization of the projects |
| `team_mapping` | Team to Sentry team | No | Maps an Imbi team slug to the Sentry team that owns new Sentry projects. A team that is not in the map uses its own slug |
| `issue_count_facts` | Issue-count facts | No | Maps a project fact name to a Sentry issue search. Default: `sentry_open_issues` = `is:unresolved` |
| `issue_period` | Issue search period | No | The Sentry `statsPeriod` of the counts, for example `14d` or `90d`. Default: `14d` |

Each fact in `issue_count_facts` must be an integer property in a project
blueprint. Add one row for each count that you want. Example:

| Fact | Sentry search |
|---|---|
| `sentry_open_issues` | `is:unresolved` |
| `sentry_unhandled_issues` | `is:unresolved error.unhandled:true` |

### Credentials

| Credential | Required | Secret | Meaning |
|---|---|---|---|
| `auth_token` | Yes | Yes | The token of a Sentry internal integration |

Make an internal integration at **Settings > Custom Integrations** in
Sentry. Give it these permissions:

| Permission | Needed for |
|---|---|
| Project: Admin | The lifecycle and the Doctor fix that create Sentry projects |
| Issue & Event: Read | The issue counts |

## Project link

Each Imbi project links to one Sentry project. The link is the
`EXISTS_IN` edge, and its identifier is the Sentry project slug. If the
project has no edge, the plugin uses the Imbi project slug. An identifier
on an existing edge always wins.

The plugin also writes the `sentry` project link. It opens the issues of
the project in Sentry, for the `issue_period`.

## Webhook actions

| Handler | Label | What it does |
|---|---|---|
| `sentry#sync_issue_counts` | Sync Sentry issue counts | Counts the issues for each search in `issue_count_facts` and writes the counts to the project |

The handler has no configuration (`{}`).

To set up the webhook:

1. In Imbi, make a webhook for the Sentry integration (see
   [Webhooks](../admin/webhooks.md)). Set these values:

    | Field | Value |
    |---|---|
    | Identifier Selector | `/data/issue/project/slug` |
    | Event Type Selector | `sentry-hook-resource` |
    | Secret | The **Client Secret** of the internal integration |

2. Add a rule with the handler `sentry#sync_issue_counts`.
3. In the Sentry internal integration, set the **Webhook URL** to the
   webhook URL from Imbi, and select the **issue** webhook.

The gateway verifies the `Sentry-Hook-Signature` header with the secret.
It drops a delivery that has no valid signature.

The action counts the issues in Sentry. It does not count the webhook
events, so a lost delivery does not make a count incorrect. If Sentry
fails, the action logs the error and changes nothing.

## Doctor checks

| Finding | Result | Fix |
|---|---|---|
| `exists-in` | Pass: the edge and the `sentry` link match the Sentry project. Fail: the Sentry project does not exist. Fail or warn: the edge or the link does not match. Warn: the configuration is incomplete or Sentry cannot be reached | **Create / link the Sentry project**, or **Repair the Sentry link** |
| `sentry-team` | Pass: only the expected team owns the Sentry project. Fail: another team, or no team, owns it. Warn: the project has no owning team | **Set the Sentry team** |
| `issue-count:<fact>` | Pass: the fact is equal to the count in Sentry. Warn: the fact is different | **Sync issue counts from Sentry** |
| `issue-counts` | Warn: Sentry cannot count the issues | None |

The fixes:

- **Create / link the Sentry project** creates the Sentry project if it
  does not exist, then writes the edge and the link. You must confirm it.
- **Repair the Sentry link** writes the edge and the link for a Sentry
  project that exists. It never creates a project.
- **Set the Sentry team** makes the expected team (from `team_mapping`,
  or the Imbi team slug) the only owner of the Sentry project. When the
  expected team already owns the project, it removes all other teams, so
  those teams lose access. When no team owns the project, it adds the
  expected team. When only other teams own it, it does nothing: add the
  expected team in Sentry first. You must confirm it, and it is not sweepable. It is offered
  only for the Sentry project with the Imbi project slug, linked by the
  plugin itself. For an identifier that someone set by hand, change the
  teams in Sentry.
- **Sync issue counts from Sentry** writes each count to its fact. It is
  sweepable, so **Apply Sync Fixes** keeps the facts current.

## Lifecycle

| Event | What it does |
|---|---|
| Created | Creates the Sentry project in the team from `team_mapping`, or links the project that exists. It does not link a Sentry project that only other teams own |
| Deleted | Nothing in Sentry. Imbi removes the edge and the link with the project, and Sentry keeps the issue history |

## Known limits

- Sentry gives an approximate count (the `X-Hits` header), with a maximum
  of 1000.
- A change of the project slug does not change the Sentry project. After
  a change of the owning team, the Doctor shows `sentry-team` as failed
  until you apply **Set the Sentry team**.
- The lifecycle does not change the teams of a Sentry project that
  exists. It only links the project, and the Doctor reports the team.
