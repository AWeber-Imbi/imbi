# SonarQube

The `sonarqube` plugin connects Imbi to a SonarQube server. It does two
things:

- When SonarQube sends a webhook, it reads the measures of the project
  and writes them to project fields, for example test coverage.
- In the project **Doctor**, it checks the link to the SonarQube project
  and the main branch, and offers fixes.

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
| `service_url` | SonarQube URL | Yes | The base URL of the SonarQube server, for example `https://sonarqube.example.com` |

### Analysis capability options

| Option | Label | Default | Meaning |
|---|---|---|---|
| `main_branch` | Expected main branch | `main` | The branch that SonarQube must use as the main branch of each project. Override it for a project type or a project whose main branch has a different name |

### Credentials

| Credential | Required | Secret | Meaning |
|---|---|---|---|
| `api_token` | Yes | Yes | A SonarQube **user** token |

Use a user token. You make it at **My Account > Security** in SonarQube.
Its prefix is `squ_`. Analysis tokens (`sqa_` global, `sqp_` project) can
call only the scanner endpoints. They get `403` from every call that this
plugin makes, also when an administrator makes them.

Give the account of the token these SonarQube permissions:

| Permission | Needed for |
|---|---|
| Browse, on the projects | All reads |
| Create Projects | The Doctor fix that creates a missing SonarQube project |
| Administer, on the project | The Doctor fix that changes the main branch, and the lifecycle delete |

## Component key

Each Imbi project links to one SonarQube project (a *component*). The link
is the `EXISTS_IN` edge, and its identifier is the component key. See
[Project links to integrations](../admin/integrations-and-plugins.md#project-links-to-integrations).

If the project has no edge, the plugin uses the key
`<owning team slug>:<project slug>`. An identifier on an existing edge
always wins, so a key that you set by hand stays.

## Webhook actions

| Handler | Label | What it does |
|---|---|---|
| `sonarqube#update_project_from_webhook` | Update Project from SonarQube Measures | Reads the configured measures from SonarQube and writes them to the project |

The handler configuration is a list of mappings. Each mapping has a
SonarQube metric key (`metric`) and a JSON Pointer to the project field
that gets the value (`path`).

Example rule:

```text
Handler: sonarqube#update_project_from_webhook
Filter:  payload.branch.isMain == true
Config:  [
           {"metric": "coverage", "path": "/test_coverage"},
           {"metric": "ncloc",    "path": "/lines_of_code"}
         ]
```

The action does these steps:

1. imbi-gateway finds the Imbi project from the component key in the
   delivery.
2. The action calls `GET /api/measures/component` with the metric keys.
3. The action sends one JSON Patch with an `add` operation for each
   measure to the Imbi API. It uses the gateway API token
   (`IMBI_GATEWAY_API_TOKEN`).

The action does not read the webhook body for the measures. It skips a
metric that SonarQube does not return. If the token or the URL is not
set, or SonarQube fails, the action logs a warning and changes nothing.

To make the webhook and its rules, see [Webhooks](../admin/webhooks.md)
and [Gateway](../gateway/index.md).

## Doctor checks

| Finding | Result | Fix |
|---|---|---|
| `service-url` | Warn: the integration has no `service_url` | None |
| `api-token` | Warn: the integration has no `api_token` | None |
| `exists-in` | Fail: no edge and no SonarQube project. Warn: no edge, but the SonarQube project exists | **Create / link the SonarQube project**, or **Repair the SonarQube project link** |
| `component` | Pass: the project exists. Fail: the edge names a project that does not exist. Warn: SonarQube cannot be reached | **Create / link the SonarQube project** |
| `canonical-url` | Fail: the API URL on the edge is not `<service_url>/api/components/show?component=<key>` | **Repair the SonarQube project link** |
| `dashboard-link` | Fail or warn: the `sonarqube` project link is not `<service_url>/dashboard?id=<key>` | **Repair the SonarQube project link** |
| `main-branch` | Fail: the expected branch exists but is not the main branch | **Track '*branch*' as the main branch** |
| `main-branch-missing` | Fail: SonarQube has no branch with the expected name | None. Run an analysis of that branch in CI, or change `main_branch` |

The fixes:

- **Create / link the SonarQube project** searches SonarQube for the key.
  If it finds no project, it creates one with the key and the project
  name. Then it writes the edge and the dashboard link. You must confirm
  it.
- **Repair the SonarQube project link** writes the edge and the dashboard
  link for a project that exists. It never creates a project.
- **Track '*branch*' as the main branch** calls
  `POST /api/project_branches/set_main`. The old main branch becomes an
  ordinary branch. You must confirm it.

No SonarQube fix is sweepable, so **Apply Sync Fixes** does not apply
them. **Remediate Findings** in **Admin > Maintenance** applies every fix,
including the fix that creates projects.

When SonarQube cannot be reached or the configuration is incomplete, the
Doctor shows `warn` findings. It does not fail.

## Lifecycle

| Event | What it does |
|---|---|
| Archive | Deletes the SonarQube project |
| Delete | Deletes the SonarQube project |

!!! warning "Archiving deletes the SonarQube project for good"

    Lifecycle is on by default, and archiving an Imbi project deletes
    its SonarQube project along with every analysis, issue, and metric
    history. Unarchiving the Imbi project or creating the SonarQube
    project again does not bring that history back. Decide whether you
    need it before you archive.

Both events call `POST /api/projects/delete` with the component key. The
key is the identifier on the `EXISTS_IN` edge. A project without an edge
is skipped: the plugin does not use the `<owning team slug>:<project
slug>` convention to find a key, because that key is a guess.
After the call, the plugin removes the edge and the `sonarqube` project
link, so Imbi does not point at a project that is gone.

Any project writer can link any key, so the plugin deletes only when the
edge names the key `<owning team slug>:<project slug>` of the project.
It skips and logs any other key. It also skips a key that another Imbi
project links through any SonarQube integration of the organization. For
a skipped key, delete the SonarQube project in SonarQube yourself. A
manual link to a key that another project holds gets a `409`, and only
an admin can change the verified key of a project.

The result of the event:

| Result | When |
|---|---|
| `ok` | SonarQube deleted the project |
| `skipped` | SonarQube has no project with the key. The edge and link are still removed. Also when the project has no `EXISTS_IN` edge, the key is not the project's convention key, another Imbi project links the key, or the integration has no `service_url` or `api_token` |
| `failed` | SonarQube refused the call, for example `403` when the token account lacks Administer on the project. On archive, the edge and link stay. On delete, Imbi has already removed the project node, so nothing is left to keep them on: the SonarQube project remains and you delete it in SonarQube yourself |

The plugin does not create SonarQube projects when you create an Imbi
project, and does not create one again when you unarchive it. Only an
analysis or the Doctor fix creates them.

After an archive or delete the project has no `EXISTS_IN` edge, so the
Doctor falls back to the `<owning team slug>:<project slug>` convention.
If the scanner reports under a custom key, say `legacy-key`, the fix
**Create / link the SonarQube project** creates a *different* project
under the convention key and the scanner keeps reporting to
`legacy-key`, where Imbi no longer looks. Before you run the fix after
an unarchive, either set the custom key on the edge again by hand (see
[Component key](#component-key)) or point the scanner at the convention
key. Only then use **Create / link the SonarQube project**.

## Known limits

- The component key convention assumes one team owns each project. A
  project without an owning team and without an edge gets only a warning.
- A component with no branch named `main_branch` cannot be fixed from
  Imbi.
