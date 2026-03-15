# Users and Groups

## Users

Every person who uses Imbi has a user account with:

- **Email** -- used for sign-in and notifications
- **Display name** -- shown throughout the UI
- **Organization memberships** -- which organizations they belong to
- **Group memberships** -- which teams they are part of

### How Users Are Created

There are three ways users get added to Imbi:

1. **Initial setup** -- the first admin user is created when you run
   the `setup` command
2. **Admin invitation** -- administrators can create user accounts from
   **Settings > Users > New User**
3. **OAuth auto-provisioning** -- when SSO is configured, users are
   automatically created the first time they sign in with their
   identity provider

### Managing Users

From **Settings > Users**, administrators can:

- View all user accounts
- Edit a user's display name, email, or role assignments
- Disable a user account (the user can no longer sign in but their
  data and history are preserved)

## Groups

Groups let you organize users into teams and assign shared permissions.
Instead of managing role assignments for each user individually, you
assign a role to a group and all members inherit it.

### Organization and Group Structure

Groups exist within organizations:

```
Organization (e.g. "Engineering")
  +-- Group (e.g. "Backend Team")
  |     +-- Alice
  |     +-- Bob
  +-- Group (e.g. "Frontend Team")
        +-- Carol
        +-- Dave
```

### Creating a Group

1. Navigate to **Settings > Groups**
2. Click **New Group**
3. Enter a name and select the organization
4. Click **Save**
5. Add members from the group detail page

### Managing Group Membership

From a group's detail page, you can:

- Add or remove members
- Change the role assigned to the group
- View all members and their individual roles

When a user is removed from a group, they lose the permissions that
were inherited from that group. Any individually assigned roles are
not affected.

!!! tip
    Use groups to model your actual team structure. When someone joins
    or leaves a team, updating their group membership automatically
    handles their permissions.
