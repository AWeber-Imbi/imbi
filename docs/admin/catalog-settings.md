# Catalog Settings

The catalog settings describe the projects of one organization. They are
in the **&lt;Org&gt; Admin** group of the Admin menu. &lt;Org&gt; is the
organization that you select in the top bar. Each setting belongs to that
organization.

| Page | Menu path | What it defines |
|---|---|---|
| Environments | **Admin > &lt;Org&gt; Admin > Environments** | Where projects run, and the order of promotion |
| Project Types | **Admin > &lt;Org&gt; Admin > Project Types** | The kinds of project, and whether they deploy or release |
| Link Definitions | **Admin > &lt;Org&gt; Admin > Link Definitions** | The types of link that a project can have |
| Default Settings | **Admin > &lt;Org&gt; Admin > Default Settings** | The version formats of the organization |
| Document Templates | **Admin > &lt;Org&gt; Admin > Document Templates** | Starter content for new documents |

The **Admin** item shows only for platform administrators. A
[blueprint](blueprints.md) can add fields to environments and project
types. The forms show those fields below the standard fields.

## Permissions

<!-- BEGIN GENERATED: scripts/docs_permissions_subset.py environment: project_type: link_definition: document_template: organization:update -->

| Permission | Lets you | Roles that have it |
|---|---|---|
| `organization:update` | Update organizations | `admin`, `developer` |
| `link_definition:create` | Create link definitions | `admin` |
| `link_definition:read` | View link definitions | `admin`, `developer`, `default`, `readonly`, `imbi-scheduler` |
| `link_definition:write` | Update link definitions | `admin`, `developer` |
| `link_definition:delete` | Delete link definitions | `admin` |
| `environment:create` | Create environments | `admin` |
| `environment:read` | View environments | `admin`, `developer`, `default`, `readonly`, `imbi-scheduler` |
| `environment:update` | Update environments | `admin` |
| `environment:delete` | Delete environments | `admin` |
| `project_type:create` | Create project types | `admin` |
| `project_type:read` | View project types | `admin`, `developer`, `default`, `readonly`, `imbi-scheduler` |
| `project_type:update` | Update project types | `admin` |
| `project_type:delete` | Delete project types | `admin` |
| `document_template:create` | Create document templates | `admin` |
| `document_template:read` | View document templates | `admin`, `developer`, `default`, `readonly`, `imbi-scheduler` |
| `document_template:write` | Update document templates | `admin` |
| `document_template:delete` | Delete document templates | `admin` |

<!-- END GENERATED -->

**Default Settings** saves to the organization, so it needs
`organization:update`. These routes are not organization routes. They use
the union of your roles in all your organizations. See
[Permissions across organizations](roles-and-permissions.md#permissions-across-organizations).

## Environments

An environment is a place where a project runs, for example `testing`,
`staging`, or `production`. Deployments, the release train, and the
promotion pipeline use environments.

### Create an environment

1. Open **Admin > &lt;Org&gt; Admin > Environments**.
2. Click **New Environment**.
3. Enter the fields in the table below.
4. Click **Create Environment**.

| Field | What to enter |
|---|---|
| Organization | Required. The organization of the environment |
| Environment Name | Required. Imbi makes the slug from the name |
| Slug | Required. You cannot change the slug later |
| Sort Order | The display order. Lower numbers show first. The promotion pipeline also goes from one environment to the next by this order |
| Allow Direct Deploys | On by default. Lets people deploy a commit or an existing release into this environment. Clear it to make promotion the only way in |
| Allow Promotion | Off by default. Lets people promote what the previous environment runs into this environment, which cuts a new release tag |
| Terminal Environment | Ends the promotion pipeline. Imbi makes no promotion step from this environment to the next one. The next environment starts a new pipeline |
| Allow Autonomous Deployments | Lets a service account that acts with the integration's own credential deploy or promote into this environment. Off by default. It does not change what people can do |
| Description | Optional |
| Icon | An icon, or an image that you upload |
| Label color | The color of the environment label, as a hex value |

**Allow Autonomous Deployments** is one of the bounds of
[ADR 0017](../api/adr/0017-autonomous-deployment-principals.md). The
deploy and rollback steps of [workflows](workflows.md) need it.

### Deploy and promote flags

**Allow Direct Deploys** and **Allow Promotion** are the `can_deploy` and
`can_promote` fields of the environment:

| Flag | Default | Effect |
|---|---|---|
| `can_deploy` | `true` | The API accepts a deploy into this environment. When it is off, the **Deployments** tab disables the deploy and roll-back buttons and says why |
| `can_promote` | `false` | The API accepts a promote into this environment. When it is off, the **Deployments** tab disables the promote form and says why |

### Delete an environment

Click the delete action in the environment list. Imbi does not check if
projects use the environment. It removes the environment and every
relationship to it.

## Project types

A project type is a kind of project, for example `REST API` or `Library`.
Each project has a project type. Blueprints, scoring policies, document
templates, and version formats can apply to some project types only.

### Create a project type

1. Open **Admin > &lt;Org&gt; Admin > Project Types**.
2. Click **New Project Type**.
3. Enter the fields in the table below.
4. Click **Create Project Type**.

| Field | What to enter |
|---|---|
| Project Type Name | Required. Imbi makes the slug from the name |
| Slug | Required. You cannot change the slug later |
| Description | Optional |
| Deployable | Projects of this type deploy into environments. They get deployment tracking and the release train |
| Releasable | Projects of this type publish a tag and a GitHub release, with no deploy step. They get the **Releases** tab |
| Icon | An icon, or an image that you upload |
| Version formats | Optional. See [Version formats](#version-formats) |

**Deployable** and **Releasable** are mutually exclusive. A project type
can have one of them, or neither.

### Delete a project type

Click the delete action in the list. Imbi does not check if projects use
the project type. It removes the project type and every relationship to
it, so those projects have no type.

## Link definitions

A link definition is a type of link that a project can have, for example
`GitHub Repository` or `Grafana Dashboard`. The **Links** card of a
project offers each link definition of the organization.

1. Open **Admin > &lt;Org&gt; Admin > Link Definitions**.
2. Click **New Link Definition**.
3. Enter the fields in the table below.
4. Save.

| Field | What to enter |
|---|---|
| Organization | Required |
| Name | Required. Imbi makes the slug from the name |
| Slug | Required. Lowercase letters, digits, hyphens, and underscores. You cannot change it later |
| Description | Optional |
| Icon | The icon that the project page shows next to the link |
| URL Template | Optional. For example `https://github.com/{organization}/{project}` |

The project link editor shows the **URL Template** as the placeholder
text of the URL field. Imbi does not replace the placeholders in curly
braces. The user enters the full URL.

A [scoring policy](scoring-policies.md) of the type **Link Presence**
checks that a project has a link of one link definition.

Imbi does not check if projects use a link definition before it deletes
it.

## Version formats

A version format is a regular expression that a release tag must match.
Imbi checks the tag when a user cuts a release or promotes a release. The
draft of the release notes also uses the formats to suggest the next
version.

The organization has a list of formats on **Admin > &lt;Org&gt; Admin >
Default Settings**. A project type can override the list.

### Organization formats

1. Open **Admin > &lt;Org&gt; Admin > Default Settings**.
2. Under **Supported version formats**, turn on the formats to accept.
3. Optional: click **Add custom format**. Enter a name and a pattern. Use
   the test field to try a version. Click **Save format**.
4. Click **Save changes**.

The built-in formats are:

| Format | Example | Pattern |
|---|---|---|
| Semantic versioning | `2.11.5` | `MAJOR.MINOR.PATCH` with optional pre-release and build metadata. A leading `v` is optional, so `v2.11.5` is also accepted |
| Calendar versioning | `2026.09.17-0` | Year, month, and day, with an optional suffix |
| Git short SHA | `7d4f2a3b` | 7 to 40 lowercase hexadecimal characters |
| Any format | `nightly-build` | Any text that is not empty |

A format list saved before this release keeps the old semantic
versioning pattern, which rejects a leading `v`. The list shows it as
the built-in row with the new pattern, and **Save changes** is enabled.
Until you save, Imbi uses the old pattern, but the test field uses the
new one. To store the new pattern, click **Save changes**. For a project
type, turn **Semantic versioning** off and on again, then save the
project type.

Use **Test a version string** to see which enabled formats accept a
version.

### Project type formats

1. Open the project type.
2. Under **Version formats**, turn on the override switch.
3. Turn on the formats to accept, or add custom formats.
4. Save the project type.

When the switch is off, the project type uses the formats of the
organization.

### How Imbi applies the formats

1. If one or more project types of the project have formats, Imbi uses the
   formats of all those project types together.
2. If not, Imbi uses the formats of the organization.
3. If neither has formats, Imbi accepts any tag.

A tag is valid when it matches one of the formats. Imbi matches the whole
tag. When a user cuts a release with a tag that matches no format, Imbi
refuses it with `400`. A promote accepts a Git commit SHA (7 to 40 lowercase
hexadecimal characters) as well as a matching tag.

## Document templates

A document template is starter content for a new document. When a user
creates a document from a template, Imbi copies the title, the content,
and the tags of the template.

1. Open **Admin > &lt;Org&gt; Admin > Document Templates**.
2. Click **New Document Template**.
3. Enter the fields in the table below.
4. Click **Save**.

| Field | What to enter |
|---|---|
| Name | Required. For example `Architecture Decision Record` |
| Slug | Required. You cannot change it later |
| Description | Optional |
| Icon | Optional |
| Default Document Title | The title of a new document |
| Content | The Markdown body of a new document |
| Default Tags | Tags that Imbi adds to a new document. The tags must exist in the organization |
| Project Types | Offer the template only for projects of these types. Leave empty to offer it for every project type |
| Sort Order | The order in the template menu |

A template also has a `type`. It sets where Imbi offers the template:

| Type | Offered for |
|---|---|
| `project` | Project documents. This is the default |
| `user` | User documents |
| `project_type` | Project type documents |
| `global` | All documents |

The form does not show the type. A template that you make in the form has
the type `project`. To set another type, send it in
`POST /organizations/{org}/document-templates` or change it with
`PATCH`. The organization documents page offers templates of every type.

## Related pages

- [Blueprints](blueprints.md)
- [Scoring Policies](scoring-policies.md)
- [Releases and Deployments](../user-guide/releases-and-deployments.md)
- [Documents and Reports](../user-guide/documents-and-reports.md)
