# Roles and Permissions

Imbi uses role-based access control (RBAC) to manage what users can
see and do. Permissions are grouped into roles, and roles are assigned
to users.

## Built-in Roles

Imbi ships with three default roles created during initial setup:

### Admin

Full access to everything: manage users, roles, organizations, teams,
blueprints, and all project operations. Assign this role to platform
administrators.

### Developer

Can view and manage projects, blueprints, and related resources. Cannot
manage users, roles, or system-level settings. This is the typical role
for engineering team members.

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
| `projects:read` | View projects and their metadata |
| `projects:write` | Create and update projects |
| `projects:delete` | Delete projects |
| `users:read` | View user profiles |
| `users:write` | Create and manage user accounts |
| `blueprints:read` | View blueprints |
| `blueprints:write` | Create and manage blueprints |
| `roles:read` | View roles and permissions |
| `roles:write` | Create and manage roles |

!!! tip
    Follow the principle of least privilege: start with the Readonly
    role and add permissions as needed, rather than starting with Admin
    and removing them.
