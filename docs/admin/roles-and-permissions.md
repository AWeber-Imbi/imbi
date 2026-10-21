# Roles and Permissions

Imbi uses role-based access control (RBAC) to manage what users can
see and do. Permissions are grouped into roles, and roles are assigned
to users.

## Built-in Roles

Imbi ships with four default roles created during initial setup:

### Admin

Full access to everything: manage users, roles, organizations, teams,
blueprints, and all project operations. Assign this role to platform
administrators.

### Developer

Can view and manage projects, blueprints, and related resources. Cannot
manage users, roles, or system-level settings. This is the typical role
for engineering team members.

### Default

Baseline read access. Imbi grants this role automatically to a user on
first login.

### Readonly

Can view all resources but cannot create, edit, or delete anything.
Useful for stakeholders who need visibility without write access.

## Assigning Roles

Roles are assigned to users within the context of an organization. A
user can have different roles in different organizations -- for example,
an admin in one org and a developer in another.

To assign a role:

1. Navigate to **Settings > Users**
2. Select the user
3. Under **Organization Memberships**, choose the role for each
   organization the user belongs to
4. Click **Save**

## Group-Based Roles

Instead of assigning roles to individual users, you can assign roles
to groups. All members of the group automatically inherit the group's
roles.

This is the recommended approach for teams:

1. Create a group (e.g. "Backend Team")
2. Assign a role to the group (e.g. "Developer")
3. Add users to the group

When a user is added to or removed from the group, their effective
permissions update immediately.

## Custom Roles

If the built-in roles do not fit your needs, administrators can create
custom roles:

1. Navigate to **Settings > Roles**
2. Click **New Role**
3. Enter a name (e.g. "Team Lead")
4. Select the permissions to include
5. Click **Save**

### Available Permissions

Permissions follow a `resource:action` pattern:

| Permission | Description |
|------------|-------------|
| `project:create` | Create projects |
| `project:read` | View projects and their metadata |
| `project:write` | Update projects |
| `project:delete` | Delete projects |
| `user:create` | Create user accounts |
| `user:read` | View user profiles |
| `user:update` | Update user accounts |
| `user:delete` | Delete user accounts |
| `blueprint:read` | View blueprints |
| `blueprint:write` | Create and update blueprints |
| `blueprint:delete` | Delete blueprints |
| `role:create` | Create roles |
| `role:read` | View roles and permissions |
| `role:update` | Update roles |
| `role:delete` | Delete roles |

### Agent, Workflow, Prompt, and Secret Permissions

The **Admin** role gets every permission. The table shows which other
built-in roles get each permission. **Default** is the role that a user gets
automatically on first login.

| Permission | Description | Developer | Default | Readonly |
|------------|-------------|:---------:|:-------:|:--------:|
| `prompt:read` | View prompts and their versions | yes | yes | yes |
| `prompt:create` | Create prompts | yes | | |
| `prompt:update` | Edit prompts and save new versions | yes | | |
| `prompt:promote` | Move prompt labels and set the default label | | | |
| `prompt:delete` | Delete prompts | | | |
| `prompt:evaluate` | Record evaluation results against prompt versions | | | |
| `agent:read` | View agents and their versions | yes | yes | yes |
| `agent:create` | Create agents | yes | | |
| `agent:write` | Update and restore agents | yes | | |
| `agent:delete` | Delete agents | | | |
| `agent_task:read` | View agent tasks and their events | yes | yes | yes |
| `agent_task:create` | Create agent tasks | yes | | |
| `agent_task:manage` | Pause, resume, cancel, and reassign agent tasks | yes | | |
| `agent_task:resolve` | Answer feedback requests and resolve approvals | yes | | |
| `workflow:read` | View workflows, their versions, and their runs | yes | yes | yes |
| `workflow:create` | Create workflows | yes | | |
| `workflow:write` | Edit, activate, and pause workflows | yes | | |
| `workflow:delete` | Delete workflows | | | |
| `workflow:run` | Start manual and test runs, and cancel runs | yes | | |
| `harness_pool:read` | View the runner pools and runners that serve the organization | | | |
| `agent_platform_config:write` | Change the base agent configuration and the plugin marketplaces | | | |
| `secret_provider:read` / `:write` | View, or change and test, secret providers | | | |
| `secret_binding:read` / `:write` | View, or change and validate, secret bindings | | | |
| `secret_grant:read` / `:write` | View and evaluate, or change, secret grants | | | |
| `secret_resolution:read` / `:manage` | View, or release, secret resolutions and revoke provider leases | | | |
| `secret_audit:read` | View secret audit events | | | |

To activate a workflow, you also need the permissions that its steps need,
for example `scheduled_task:create` for a Schedule step and
`webhook:update` for a Webhook step. See the step table in
[Workflows](workflows.md).

Only platform administrators (users with `is_admin`) can change runner
pools. This is not a permission, because an organization administrator can
grant a permission to a role.

See [Agents](agents.md), [Agent tasks](agent-tasks.md),
[Workflows](workflows.md), [Prompts](prompts.md), and [Secrets](secrets.md).

### Service Roles

`imbi-api setup` also seeds a role for each internal service account. You do
not assign these roles to people.

| Role | New grants in 2.38 |
|------|--------------------|
| `imbi-scheduler` | `agent:read`, `agent_task:create`, `agent_task:read`, `workflow:run` |
| `imbi-gateway` | `agent_task:create`, `workflow:run` |
| `imbi-workflows` | `project:read`, `project:deployment:read`, `project:deployment:write`, `scheduled_task:read`, `scheduled_task:create`, `scheduled_task:write`, `scheduled_task:delete` |

The `imbi-workflows` role does not include `integration:act-as-service`. An
operator must grant it, as ADR 0017 requires for every autonomous principal.

After an upgrade, run `imbi-api setup-permissions` to add new permissions and
refresh the grants of the built-in roles. See
[Initial Setup](../getting-started/setup.md#applying-upgrades).

!!! tip
    Follow the principle of least privilege: start with the Readonly
    role and add permissions as needed, rather than starting with Admin
    and removing them.
