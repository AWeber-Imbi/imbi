# Users and Groups

## Users

Users represent individuals who interact with Imbi. Each user has:

- **Email** - Unique identifier and login credential
- **Display name** - Shown in the UI
- **Organization memberships** - Users belong to one or more organizations
- **Group memberships** - Users can be members of groups for team-based access

### Creating Users

Users can be created in several ways:

1. **Setup command** - The initial admin user is created during setup
2. **Admin API** - Administrators can create users via the REST API
3. **OAuth auto-creation** - Users are automatically created on first OAuth login
   (when enabled)

## Groups

Groups provide a way to organize users and assign shared permissions. Each
group can have roles assigned to it, and all members of the group inherit
those permissions.

### Group Hierarchy

Groups exist within organizations:

```
Organization
  └── Group
       ├── User A
       └── User B
```

### Creating Groups

Groups are created via the REST API or the admin UI:

```
POST /api/groups
{
  "name": "Backend Team",
  "organization_id": "org-id"
}
```
