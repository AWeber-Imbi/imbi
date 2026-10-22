# Roles and Permissions

Imbi uses role-based access control. A permission lets a principal do one
action, for example `project:write`. A role is a set of permissions. A
user or a service account gets a role from a membership in an
organization. Teams do not give roles.

A platform administrator (`is_admin`) passes every permission check. This
is not the same as the `admin` role. See
[Platform administrators](users-teams-organizations.md#platform-administrators).

## Built-in roles

`imbi-api setup` seeds seven roles. Four roles are for people. Three roles
are for the service accounts of Imbi services.

| Role | Name | For | What it gives |
|---|---|---|---|
| `admin` | Administrator | People | Every permission |
| `developer` | Developer | People | Read most resources. Create and change projects, blueprints, agents, agent tasks, workflows, prompts, scheduled tasks, documents, comments, and tags. Change organizations, teams, integrations, webhooks, and link definitions. No `role:read` and no `operations_log:read` |
| `default` | Default | People | Read most resources, and rescore projects (`scoring_policy:rescore`). Imbi gives this role to a new user on first sign-in |
| `readonly` | Read Only | People | The `default` role without `scoring_policy:rescore` |
| `imbi-scheduler` | Imbi Scheduler | `imbi-scheduler` | Manage and run scheduled tasks, start agent tasks and workflow runs, and read the resources that a task looks at |
| `imbi-gateway` | Imbi Gateway | `imbi-gateway` | Change projects and record releases, find users by identity, start agent tasks and workflow runs |
| `imbi-workflows` | Imbi Workflows | `imbi-workflows` | Deploy projects and manage the scheduled tasks of schedule triggers |

`default` and `readonly` do not include the read permissions for secrets,
runner pools, service accounts, auth providers, MCP servers, and scoring
policies. The [permission table](#permission-table) shows the full grants.

The built-in roles are system roles. You cannot change their permissions
or delete them. After an upgrade, run `imbi-api setup-permissions` to add
new permissions and refresh the grants of the built-in roles. See
[Initial Setup](../getting-started/setup.md#applying-upgrades).

The `imbi-workflows` role does not include `integration:act-as-service`.
An operator must grant it, as ADR 0017 requires for every autonomous
principal.

## Assign a role

1. Open **Admin > Global Admin > User Management**.
2. Click the user.
3. Click **Edit User**.
4. Under **Memberships**, select the organization and select the role.
5. Click **Save Changes**.

See [Users, Teams, and Organizations](users-teams-organizations.md).

## Create a custom role

Roles are global. You can use one role in each organization.

1. Open **Admin > Global Admin > Roles**.
2. Click **New Role**.
3. Enter the name and the slug, for example "Team Lead".
4. Under **Permissions**, select the permissions.
5. Click **Create Role**.

!!! tip
    Use the principle of least privilege. To give more than `readonly`,
    create a custom role with the permissions of `readonly`, then add only
    the permissions that are necessary. Do not start with `admin` and
    remove permissions.

## Permissions across organizations

A user can be a member of many organizations, with a different role in
each. Imbi uses two rules to calculate the permissions of a request:

1. **Organization routes.** These routes use only the role in the
   organization of the path. A principal that is not a member of that
   organization gets `403 organization_forbidden`. A platform
   administrator must also be a member.
2. **All other routes.** These routes use the union of the roles in all
   the organizations of the principal.

An API key can have scopes. On both types of route, the scopes of the key
limit the permissions that the roles give.

The organization routes are these routes under
`/organizations/{org_slug}/`:

| Area | Routes |
|---|---|
| Agents | `agents` |
| Agent tasks | `agent-tasks` |
| Agent usage | `agent-usage` |
| Agent platform | `agent-platform-config`, `agent-marketplaces` |
| Workflows | `workflows`, `workflow-step-types`, `workflow-runs` |
| Secrets | `secret-providers`, `secret-bindings`, `secret-grants`, `secret-resolutions`, `secret-audit-events` |

These requests also use only the role in one organization:

- `GET /harness/pools` with the `organization` parameter.
- The secret binding that you make when you bind a credential to an MCP
  server.
- A label move on the system prompt of an agent (see
  [Prompt labels](#prompt-labels)).

All other routes use the union, for example projects, teams, blueprints,
prompts, and users.

Example: a user has `developer` in organization A and `readonly` in
organization B. The user can create a project in organization B, because
the projects routes use the union. The user cannot create an agent in
organization B, because the agents routes use only the `readonly` role.

!!! warning "Known limitation"
    The UI shows or hides buttons with the union of your roles. On the
    organization routes, the API uses only the role in that organization.
    Thus the UI can show a button that returns 403 when you click it. For
    example, a user with `agent_task:manage` in one organization sees
    **Pause** and **Cancel** on the tasks of another organization. See
    [issue #458](https://github.com/AWeber-Imbi/imbi/issues/458).

## Special rules

### Prompt labels

`prompt:promote` lets you move any prompt label. No built-in role other
than `admin` has it.

The system prompt of an agent is the prompt `agents/<org>.<agent>`. To
move a label of this prompt, `agent:write` in that organization is also
sufficient. Thus a developer can save a change to an agent and make the
agent use it. See [Prompts](prompts.md) and [Agents](agents.md).

### Runner pools

Only platform administrators can change runner pools. This is not a
permission, because an organization administrator can grant a permission
to a role. `harness_pool:read` lets a member see the pools that serve the
organization.

### Workflow activation

To activate a workflow, you also need the permissions that its steps
need. For example, a Schedule step needs `scheduled_task:create`, and a
Webhook step needs `webhook:update`. See [Workflows](workflows.md).

## Permission table

Permissions follow a `resource:action` pattern. The table shows each
permission that `imbi-api setup` seeds, and the built-in roles that have
it.

<!-- BEGIN GENERATED: scripts/docs_permissions_table.py -->

| Permission | Description | `admin` | `developer` | `default` | `readonly` | `imbi-scheduler` | `imbi-gateway` | `imbi-workflows` |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `user:create` | Create new users | yes |  |  |  |  |  |  |
| `user:read` | View user information | yes | yes | yes | yes | yes | yes |  |
| `user:update` | Update user information | yes |  |  |  |  |  |  |
| `user:delete` | Delete users | yes |  |  |  |  |  |  |
| `role:create` | Create new roles | yes |  |  |  |  |  |  |
| `role:read` | View role information | yes |  | yes | yes | yes |  |  |
| `role:update` | Update role information | yes |  |  |  |  |  |  |
| `role:delete` | Delete roles | yes |  |  |  |  |  |  |
| `organization:create` | Create organizations | yes |  |  |  |  |  |  |
| `organization:read` | View organizations | yes | yes | yes | yes | yes |  |  |
| `organization:update` | Update organizations | yes | yes |  |  |  |  |  |
| `organization:delete` | Delete organizations | yes |  |  |  |  |  |  |
| `team:create` | Create teams | yes |  |  |  |  |  |  |
| `team:read` | View teams | yes | yes | yes | yes | yes |  |  |
| `team:update` | Update teams | yes | yes |  |  |  |  |  |
| `team:delete` | Delete teams | yes |  |  |  |  |  |  |
| `blueprint:read` | View blueprints | yes | yes | yes | yes | yes |  |  |
| `blueprint:write` | Create/update blueprints | yes | yes |  |  |  |  |  |
| `blueprint:delete` | Delete blueprints | yes |  |  |  |  |  |  |
| `project:create` | Create projects | yes | yes |  |  |  |  |  |
| `project:read` | View projects | yes | yes | yes | yes | yes | yes | yes |
| `project:write` | Update projects | yes | yes |  |  |  | yes |  |
| `project:delete` | Delete projects | yes |  |  |  |  |  |  |
| `link_definition:create` | Create link definitions | yes |  |  |  |  |  |  |
| `link_definition:read` | View link definitions | yes | yes | yes | yes | yes |  |  |
| `link_definition:write` | Update link definitions | yes | yes |  |  |  |  |  |
| `link_definition:delete` | Delete link definitions | yes |  |  |  |  |  |  |
| `mcp_server:create` | Create MCP servers | yes |  |  |  |  |  |  |
| `mcp_server:read` | View MCP servers | yes |  |  |  |  |  |  |
| `mcp_server:update` | Update MCP servers | yes |  |  |  |  |  |  |
| `mcp_server:delete` | Delete MCP servers | yes |  |  |  |  |  |  |
| `ai_model:create` | Create AI providers and models | yes |  |  |  |  |  |  |
| `ai_model:read` | View AI providers and models | yes | yes | yes | yes | yes |  |  |
| `ai_model:update` | Update AI providers and models | yes |  |  |  |  |  |  |
| `ai_model:delete` | Delete AI providers and models | yes |  |  |  |  |  |  |
| `ai_model:credentials` | Set or remove AI provider credentials | yes |  |  |  |  |  |  |
| `prompt:create` | Create prompts | yes | yes |  |  |  |  |  |
| `prompt:read` | View prompts and their versions | yes | yes | yes | yes |  |  |  |
| `prompt:update` | Edit prompts and save new versions | yes | yes |  |  |  |  |  |
| `prompt:promote` | Move prompt labels and set the default label | yes |  |  |  |  |  |  |
| `prompt:delete` | Delete prompts | yes |  |  |  |  |  |  |
| `prompt:evaluate` | Record evaluation results against prompt versions | yes |  |  |  |  |  |  |
| `environment:create` | Create environments | yes |  |  |  |  |  |  |
| `environment:read` | View environments | yes | yes | yes | yes | yes |  |  |
| `environment:update` | Update environments | yes |  |  |  |  |  |  |
| `environment:delete` | Delete environments | yes |  |  |  |  |  |  |
| `project_type:create` | Create project types | yes |  |  |  |  |  |  |
| `project_type:read` | View project types | yes | yes | yes | yes | yes |  |  |
| `project_type:update` | Update project types | yes |  |  |  |  |  |  |
| `project_type:delete` | Delete project types | yes |  |  |  |  |  |  |
| `integration:create` | Create integrations | yes |  |  |  |  |  |  |
| `integration:read` | View integrations | yes | yes | yes | yes | yes |  |  |
| `integration:update` | Update integrations | yes | yes |  |  |  |  |  |
| `integration:delete` | Delete integrations | yes |  |  |  |  |  |  |
| `webhook:create` | Create webhooks | yes |  |  |  |  |  |  |
| `webhook:read` | View webhooks | yes | yes | yes | yes | yes |  |  |
| `webhook:update` | Update webhooks | yes | yes |  |  |  |  |  |
| `webhook:delete` | Delete webhooks | yes |  |  |  |  |  |  |
| `upload:create` | Upload files | yes | yes |  |  |  |  |  |
| `upload:read` | View and download uploads | yes | yes | yes | yes | yes |  |  |
| `upload:delete` | Delete uploads | yes |  |  |  |  |  |  |
| `service_account:create` | Create service accounts | yes |  |  |  |  |  |  |
| `service_account:read` | View service accounts | yes |  |  |  |  |  |  |
| `service_account:update` | Update service accounts | yes |  |  |  |  |  |  |
| `service_account:delete` | Delete service accounts | yes |  |  |  |  |  |  |
| `operations_log:create` | Create operations log entries | yes |  |  |  |  |  |  |
| `operations_log:read` | View operations log entries | yes |  | yes | yes | yes |  |  |
| `operations_log:update` | Update operations log entries | yes |  |  |  |  |  |  |
| `operations_log:delete` | Delete operations log entries | yes |  |  |  |  |  |  |
| `component:read` | View package governance and the package reports | yes | yes | yes | yes |  |  |  |
| `component:write` | Mark packages, record advisories, and add package notes | yes |  |  |  |  |  |  |
| `tag:create` | Create tags | yes | yes |  |  |  |  |  |
| `tag:read` | View tags | yes | yes | yes | yes | yes |  |  |
| `tag:write` | Update tags | yes | yes |  |  |  |  |  |
| `tag:delete` | Delete tags | yes |  |  |  |  |  |  |
| `document:create` | Create project documents | yes | yes |  |  |  |  |  |
| `document:read` | View project documents | yes | yes | yes | yes | yes |  |  |
| `document:write` | Update project documents | yes | yes |  |  |  |  |  |
| `document:delete` | Delete project documents | yes | yes |  |  |  |  |  |
| `document:analytics:read` | View aggregate document read analytics | yes | yes | yes | yes |  |  |  |
| `document:analytics:read_identities` | View which people read a document | yes |  |  |  |  |  |  |
| `comment:create` | Create document comments | yes | yes |  |  |  |  |  |
| `comment:write` | Update document comments | yes | yes |  |  |  |  |  |
| `comment:delete` | Delete document comments | yes | yes |  |  |  |  |  |
| `auth_providers:read` | View login auth provider configuration | yes |  |  |  |  |  |  |
| `auth_providers:write` | Create, update, and delete login auth provider configuration | yes |  |  |  |  |  |  |
| `scoring_policy:read` | View scoring policies | yes |  |  |  |  |  |  |
| `scoring_policy:write` | Create/update scoring policies | yes |  |  |  |  |  |  |
| `scoring_policy:delete` | Delete scoring policies | yes |  |  |  |  |  |  |
| `scoring_policy:rescore` | Trigger rescore for a single project | yes | yes | yes |  |  |  |  |
| `scoring_policy:rescore_all` | Trigger bulk project rescore | yes |  |  |  |  |  |  |
| `document_template:create` | Create document templates | yes |  |  |  |  |  |  |
| `document_template:read` | View document templates | yes | yes | yes | yes | yes |  |  |
| `document_template:write` | Update document templates | yes |  |  |  |  |  |  |
| `document_template:delete` | Delete document templates | yes |  |  |  |  |  |  |
| `agent:create` | Create agents | yes | yes |  |  |  |  |  |
| `agent:read` | View agents and their versions | yes | yes | yes | yes | yes |  |  |
| `agent:write` | Update and restore agents | yes | yes |  |  |  |  |  |
| `agent:delete` | Delete agents | yes |  |  |  |  |  |  |
| `agent_task:read` | View agent tasks and their events | yes | yes | yes | yes | yes |  |  |
| `agent_task:create` | Create agent tasks | yes | yes |  |  | yes | yes |  |
| `agent_task:manage` | Pause, resume, cancel, and reassign agent tasks | yes | yes |  |  |  |  |  |
| `agent_task:resolve` | Answer feedback requests and resolve approvals of agent tasks | yes | yes |  |  |  |  |  |
| `workflow:read` | View workflows, their versions, and their runs | yes | yes | yes | yes |  |  |  |
| `workflow:create` | Create workflows | yes | yes |  |  |  |  |  |
| `workflow:write` | Edit, activate, and pause workflows | yes | yes |  |  |  |  |  |
| `workflow:delete` | Delete workflows | yes |  |  |  |  |  |  |
| `workflow:run` | Start manual and test runs of workflows, and cancel runs | yes | yes |  |  | yes | yes |  |
| `harness_pool:read` | View the runner pools and runners that serve the organization | yes |  |  |  |  |  |  |
| `agent_platform_config:write` | Change the base agent configuration and the plugin marketplaces | yes |  |  |  |  |  |  |
| `secret_provider:read` | View secret providers | yes |  |  |  |  |  |  |
| `secret_provider:write` | Create, change, delete, and test secret providers | yes |  |  |  |  |  |  |
| `secret_binding:read` | View secret bindings | yes |  |  |  |  |  |  |
| `secret_binding:write` | Create, change, delete, and validate secret bindings | yes |  |  |  |  |  |  |
| `secret_grant:read` | View secret grants and evaluate them | yes |  |  |  |  |  |  |
| `secret_grant:write` | Create, change, and delete secret grants | yes |  |  |  |  |  |  |
| `secret_resolution:read` | View secret resolutions | yes |  |  |  |  |  |  |
| `secret_resolution:manage` | Release secret resolutions and revoke provider leases | yes |  |  |  |  |  |  |
| `secret_audit:read` | View secret audit events | yes |  |  |  |  |  |  |
| `admin:plugins:read` | View installed plugins | yes |  |  |  |  |  |  |
| `admin:plugins:manage` | Install and uninstall plugins | yes |  |  |  |  |  |  |
| `admin:maintenance:read` | View global maintenance operations | yes |  |  |  |  |  |  |
| `admin:maintenance:manage` | Run and cancel global maintenance operations | yes |  |  |  |  |  |  |
| `project:configuration:read` | Read project configuration via plugins | yes |  |  |  |  |  |  |
| `project:configuration:read_secrets` | Read secret configuration values via plugins | yes |  |  |  |  |  |  |
| `project:configuration:write` | Write project configuration via plugins | yes |  |  |  |  |  |  |
| `project:logs:read` | Read project logs via plugins | yes |  |  |  |  |  |  |
| `project:deployment:read` | Read project deployment state via plugins | yes |  |  |  |  |  | yes |
| `project:deployment:write` | Trigger deployments and promotions via plugins | yes |  |  |  |  |  | yes |
| `project:commits:read` | Read commit history synced via plugins | yes |  |  |  |  |  |  |
| `project:commits:write` | Trigger commit-history sync via plugins | yes |  |  |  |  |  |  |
| `project:pull-requests:read` | Read pull request history synced via plugins | yes |  |  |  |  |  |  |
| `project:pull-requests:write` | Trigger pull-request sync via plugins | yes |  |  |  |  |  |  |
| `search:read` | Search nodes by semantic similarity | yes | yes | yes | yes | yes |  |  |
| `me:identities:manage` | Connect, refresh, and disconnect own third-party identities | yes | yes | yes | yes |  |  |  |
| `admin:identities:read` | List identity connections across users (audit / support) | yes |  |  |  |  |  |  |
| `admin:identities:revoke` | Force-revoke another user's identity connection | yes |  |  |  |  |  |  |
| `admin:events:read` | List events across every organization (audit / support) | yes |  |  |  |  |  |  |
| `admin:dashboard:read` | View the admin system-health dashboard | yes |  |  |  |  |  |  |
| `scheduled_task:read` | View scheduled tasks and their run history | yes | yes | yes | yes | yes |  | yes |
| `scheduled_task:create` | Create scheduled tasks | yes | yes |  |  | yes |  | yes |
| `scheduled_task:write` | Update, pause, and resume scheduled tasks | yes | yes |  |  | yes |  | yes |
| `scheduled_task:delete` | Delete scheduled tasks | yes | yes |  |  | yes |  | yes |
| `scheduled_task:run` | Run scheduled tasks on demand and cancel in-flight runs | yes | yes |  |  | yes |  |  |
| `scheduled_task:admin` | Manage other principals' and system scheduled tasks | yes |  |  |  | yes |  |  |
| `scheduler:impersonate` | Schedule tasks that run as another user | yes |  |  |  |  |  |  |
| `integration:act-as-service` | Use an Integration's own credential instead of the principal's identity | yes |  |  |  |  |  |  |

<!-- END GENERATED -->

See [Agents](agents.md), [Agent tasks](agent-tasks.md),
[Workflows](workflows.md), [Prompts](prompts.md), and
[Secrets](secrets.md).
