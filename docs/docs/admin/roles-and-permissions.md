# Roles and Permissions

Imbi uses a role-based access control (RBAC) system for authorization.

## Permissions

Permissions are fine-grained access controls in the format
`resource:action`. For example:

- `projects:read` - View projects
- `projects:write` - Create and update projects
- `projects:delete` - Delete projects
- `users:read` - View user profiles
- `users:write` - Create and update users
- `blueprints:read` - View blueprints
- `blueprints:write` - Create and update blueprints

## Roles

Roles are named collections of permissions. Imbi ships with three
default roles:

### Admin

Full access to all resources and operations.

### Developer

Read and write access to projects, blueprints, and related resources.
Cannot manage users, roles, or system settings.

### Readonly

Read-only access to all resources. Cannot create, update, or delete
anything.

## Custom Roles

Administrators can create custom roles with any combination of
permissions via the REST API:

```
POST /api/roles
{
  "name": "Team Lead",
  "permissions": [
    "projects:read",
    "projects:write",
    "users:read",
    "blueprints:read"
  ]
}
```

## Assigning Roles

Roles are assigned to users within the context of an organization. A user
can have different roles in different organizations.

Roles can also be assigned to groups. All members of the group inherit the
group's roles in addition to any individually assigned roles.
