# GitHub

The `github` plugin connects Imbi to GitHub. One plugin serves
github.com, GitHub Enterprise Cloud (GHEC) tenants, and GitHub Enterprise
Server (GHES) appliances. Make one integration for each GitHub host.

It can do these things:

- Connect users to GitHub, and sign users in to Imbi.
- Read refs and commits, cut tags and releases, and create GitHub
  deployments.
- Create, rename, archive, transfer, and delete the repository of a
  project.
- Record commit, tag, and pull request history from webhooks.
- Check the repository link and the repository homepage in the Doctor.

## Capabilities

| Capability | Label | Default | Scope |
|---|---|---|---|
| `identity` | Sign in with GitHub | Off | Organization-wide. Can sign users in |
| `deployment` | Deployments | On | Project-scoped |
| `lifecycle` | Repository lifecycle | On | Project-scoped |
| `webhook-actions` | Webhook actions | On | Project-scoped |
| `commit-sync` | Commit history sync | On | Project-scoped |
| `pr-sync` | Pull request sync | On | Project-scoped |
| `analysis` | Project doctor | On | Project-scoped |

## Configuration

### Options

| Option | Label | Default | Meaning |
|---|---|---|---|
| `flavor` | Flavor | (required) | `github` (github.com), `ghec` (GitHub Enterprise Cloud), or `ghes` (GitHub Enterprise Server) |
| `host` | Host | (empty) | The tenant host for `ghec`, for example `tenant.ghe.com`, or the appliance host name for `ghes`. Not used for `github` |
| `mainline_branches` | Mainline branches (space-separated) | `main master` | Branches that your repositories deploy from. Deployment resync does not look for a GitHub release for a deployment of one of these branches. Commas or spaces separate the names |
| `active_scan_limit` | Active deployment scan limit | `10` | How many deployments for each environment the active-state scan reads, newest first. The maximum is 100 |

### Identity capability options

| Option | Label | Default | Meaning |
|---|---|---|---|
| `default_scopes` | Default scopes (space-separated) | `read:user user:email repo workflow` | The OAuth scopes to request |

### Deployment capability options

| Option | Label | Default | Meaning |
|---|---|---|---|
| `artifact_workflow` | Release workflow | (empty) | The workflow file name, for example `release.yml`, or its numeric ID. Imbi dispatches it to build the release artifact before a deployment. The workflow must have `on: workflow_dispatch` and must exist on the default branch. Leave it empty if you build artifacts outside Imbi |
| `artifact_version_input` | Version input name | `version` | The `workflow_dispatch` input that gets the release version. GitHub accepts 10 inputs at most for each dispatch |

To send more workflow inputs for each environment, set the environment
payloads of the assignment. See
[Assignments](../admin/integrations-and-plugins.md#assignments).

### Lifecycle capability options

| Option | Label | Default | Meaning |
|---|---|---|---|
| `create_org` | Default org for repo creation | (empty) | The GitHub organization for a new repository when no `org_mapping` entry matches. Supports `${project_slug}`, `${org_slug}`, `${team_slug}`, `${project_type_slug}`, and `${project_id}`. If it is empty and no entry matches, Imbi creates no repository |
| `org_mapping` | Project-type to org overrides | (empty) | A map from a project type slug to a GitHub organization. The first project type of the project with an entry wins over `create_org` |
| `create_visibility` | Visibility for created repos | (empty) | `private`, `internal`, or `public`. If it is empty, Imbi uses `internal` for `ghec` and `ghes`, and `public` for `github` |
| `archive_target_org` | Transfer to org on archive | (empty) | When set, Imbi transfers the repository to this organization before it archives it. Leave it empty to archive in place |

### Credentials

All credentials are optional. Set the credentials for the features that
you use. See [Setup choices](#setup-choices).

| Credential | Secret | Meaning |
|---|---|---|
| `access_token` | Yes | A personal access token or a service token |
| `app_id` | No | The GitHub App ID |
| `private_key` | Yes | The GitHub App private key, as PEM or as base64-encoded PEM |
| `installation_id` | No | The GitHub App installation ID. If it is empty, Imbi finds the installation from the repository |
| `client_id` | No | The OAuth client ID, for the `identity` capability |
| `client_secret` | Yes | The OAuth client secret, for the `identity` capability |

## Setup choices

Each feature uses one of three credentials.

| Credential | Fields | Used by |
|---|---|---|
| User identity | `client_id`, `client_secret`, and a connection of each user | `identity`, and the calls a user makes from the UI |
| GitHub App | `app_id`, `private_key`, optional `installation_id` | `commit-sync`, `pr-sync`, `deployment` with no user, the Doctor |
| Token | `access_token` | The same as the GitHub App, plus `lifecycle` |

When both a token and GitHub App credentials are set, Imbi uses the token.

### User identity

Each user connects GitHub at **Settings > Connections**. Imbi then calls
GitHub with the token of that user. The flow is the OAuth web flow. Use
the client ID and the client secret of a GitHub OAuth App or of a GitHub
App.

Register the callback URL from the identity capability row of the
integration page with GitHub. See
[Identity connections](../admin/integrations-and-plugins.md#identity-connections).
If the provider returns a refresh token, Imbi refreshes the user token.

### GitHub App

Imbi signs a JWT with the App private key and gets a short-lived
installation token. It keeps the token in memory until shortly before it
expires. No long-lived token is stored. If `installation_id` is empty,
Imbi asks GitHub for the installation of each repository.

Each operation asks only for the permissions that it needs. Give the App
the permissions of the features that you use:

| Permission | Needed for |
|---|---|
| Contents: Read | Commits, tags, compare, releases, and git notes |
| Contents: Write | Cut a tag or create a release |
| Checks: Read | The CI status of a commit |
| Actions: Read | Workflow runs and deployment resync |
| Actions: Write | Dispatch the release workflow (`artifact_workflow`) |
| Deployments: Read | Deployment status and history |
| Deployments: Write | Create a deployment |
| Pull requests: Read | Pull request sync |

Install the App on each repository that Imbi must read.

### Token

A token works for all service features. The scope of a token is fixed when
you make it. Imbi cannot reduce it.

The `lifecycle` capability uses the identity token of the acting user, or
`access_token`. It never uses GitHub App credentials. Repository
create, archive, and transfer need admin access to the repository. A
transfer also needs admin access to the target organization.

## Repository link

Each project links to one repository through the `EXISTS_IN` edge. See
[Project links to integrations](../admin/integrations-and-plugins.md#project-links-to-integrations).
The GitHub plugin writes these values:

| Value | Content |
|---|---|
| Identifier | The numeric repository ID. The plugin also records it as verified |
| API URL | `<API base>/repositories/<id>`. This URL does not change when the repository is renamed |
| Dashboard link | The repository web URL, with the integration slug as the key |
| `github-repository` link | The repository web URL |

## Webhook actions

| Handler | Label | Usual event | What it records |
|---|---|---|---|
| `github#sync_commits` | Sync Commit History | `push` | The commits of the push. Imbi reads them through the compare API, so the 20-commit limit of the push body does not apply |
| `github#sync_tags` | Sync Tag History | `push` of a tag | The pushed tag. With `reconcile_all: true`, all tags of the repository |
| `github#sync_pull_requests` | Sync Pull Request History | `pull_request` | The pull request |

These actions use the GitHub App or the token. They do not use a user
identity. Imbi publishes the rows to Iggy, and the ClickHouse sink writes
them to the `commits`, `tags`, and `pull_requests` tables.

Use the rule filter to select branches and tags. The webhook body is under
`payload`. For example: `payload.ref == "refs/heads/main"` or
`payload.ref.startsWith("refs/tags/")`. See
[Webhook filter expressions](../gateway/webhook-filter-expressions.md).

Each action has a handler configuration. The defaults fit the GitHub
webhook body. These are the fields:

| Field | Actions | Default | Meaning |
|---|---|---|---|
| `repository_selector` | All | `/payload/repository/full_name` | The `owner/repo` of the delivery |
| `repo_api_url_selector` | All | `/payload/repository/url` | The repository API URL, used to find the API host |
| `api_base_url` | All | (empty) | Set the API base URL. If it is empty, Imbi uses the integration host, then the repository URL in the body |
| `before_selector` | `sync_commits` | `/payload/before` | The SHA before the push |
| `after_selector` | `sync_commits`, `sync_tags` | `/payload/after` | The SHA after the push |
| `ref_selector` | `sync_commits`, `sync_tags` | `/payload/ref` | The pushed ref |
| `initial_limit` | `sync_commits` | `100` | For a new branch with no stored commits, the number of recent commits to read |
| `reconcile_all` | `sync_tags` | `false` | Also record all tags of the repository |
| `action_selector` | `sync_pull_requests` | `/payload/action` | The pull request action |
| `pr_selector` | `sync_pull_requests` | `/payload/pull_request` | The pull request object |

On the webhook, set the identifier selector to the repository ID, for
example `/repository/id`. imbi-gateway uses it to find the project. To
make the webhook, see [Webhooks](../admin/webhooks.md) and
[Gateway](../gateway/index.md).

## Lifecycle

| Imbi event | What the plugin does |
|---|---|
| Project created | Creates a repository with the project slug as the name in the organization from `org_mapping` or `create_org`. It sets the description, the visibility, and the homepage (the Imbi page of the project). If the repository exists, it links it |
| Project updated | Renames the repository to the project slug and updates the description and the homepage. If the repository does not exist, creates it in the organization from `org_mapping` or `create_org` |
| Project relocated | Transfers the repository when the target organization changes |
| Project archived | Archives the repository. With `archive_target_org`, transfers it to that organization first |
| Project unarchived | Unarchives the repository where it is. It does not transfer it back |
| Project deleted | Deletes the repository. This happens only when **Also delete the associated repository** is selected in the delete dialog. The box is selected by default |

A failed lifecycle call does not stop or undo the change in Imbi.

## Doctor checks

| Finding | Result | Fix |
|---|---|---|
| `connection` | Warn: the `flavor` and `host` options do not give a GitHub host | None |
| `exists-in` | Pass: the edge exists. Warn: no edge | **Create the EXISTS_IN edge from GitHub** |
| `canonical-url` | Pass: Imbi can fetch the repository. Fail: `404`, a token that GitHub refused, or another error | None |
| `identifier-type` | Fail: the identifier is not an integer | **Repair the EXISTS_IN edge from GitHub** |
| `identifier-match` | Fail: the identifier is not the repository ID | **Repair the EXISTS_IN edge from GitHub** |
| `identifier-verified` | Warn: the plugin did not write the identifier from GitHub | **Verify the EXISTS_IN edge from GitHub** |
| `canonical-url-shape` | Fail: the API URL is not `<API base>/repositories/<id>` | **Repair the EXISTS_IN edge from GitHub** |
| `dashboard-url-match` | Fail or warn: the dashboard link is not the repository web URL | **Set the dashboard link from GitHub** |
| `github-repository-link-match` | Fail or warn: the `github-repository` link is not the repository web URL | **Set the github-repository link from GitHub** |
| `homepage-url-match` | Fail: the repository homepage is a different URL. Warn: no homepage, or `IMBI_UI_URL` is not set | **Set the repository homepage to the project's Imbi page** |

### identifier-verified

The `github_app` secret provider issues GitHub tokens to agent tasks only
for a repository ID that the plugin verified. An edge that a user made or
edited by hand is not verified. The fix reads the repository from GitHub
and writes the edge again, which verifies it. See
[Secrets](../admin/secrets.md).

### homepage-url-match

The expected homepage is the Imbi page of the project. Imbi builds it from
`IMBI_UI_URL`. The fix sends `PATCH /repos/{owner}/{repo}` with the new
homepage. It is the only GitHub Doctor fix that writes to GitHub. The
other fixes write to Imbi only. The credential must be able to change the
repository settings.

The Doctor uses the identity of the acting user first. If there is none,
it uses the GitHub App or the token.

## Known limits

- One integration serves one GitHub host. Make a second integration for a
  second host.
- The `lifecycle` capability cannot use GitHub App credentials.
- Unarchive does not move a repository back to its first organization.
  Imbi does not record that organization.
- The ref list of a repository is limited to 1000 branches and tags.
