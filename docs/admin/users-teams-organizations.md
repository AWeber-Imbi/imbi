# Users, Teams, and Organizations

Imbi has three types of entity for people:

| Entity | What it is | Gives permissions |
|---|---|---|
| Organization | The top-level unit. Projects, teams, agents, workflows, and secrets belong to one organization | Yes. A member has one role in each organization |
| Team | A group of users in one organization. Teams own projects, agents, and workflows | No |
| User | One person. A user is a member of one or more organizations | Only through the role in each organization |

Permissions come only from roles. A user gets a role from a membership in
an organization. A team does not have a role. See
[Roles and Permissions](roles-and-permissions.md).

The **Admin** item in the top bar shows only for platform administrators
(users with `is_admin`). All menu paths on this page start from **Admin**.

## Organizations

An organization holds the data of one unit of your company. Each project,
team, agent, workflow, and secret belongs to one organization.

The top bar has an organization selector. It lists every organization.
The pages for projects, agents, and workflows, and the **&lt;Org&gt; Admin**
menu, show the data of the organization that you select.

### Create an organization

1. Open **Admin > Global Admin > Organizations**.
2. Click **New Organization**.
3. Enter the name and the slug. The slug goes into URLs and agent prompt
   names. Use lowercase letters, digits, and hyphens.
4. Click **Create Organization**.

`imbi-api setup` creates the first organization, with the slug `default`.

### Membership

A membership connects a user to an organization. Each membership has one
role. A user can be a member of many organizations, with a different role
in each. For example, a user can have `developer` in one organization and
`readonly` in another.

To use the agents, agent tasks, workflows, and secrets of an
organization, a user must be a member of that organization. This is also
true for a platform administrator. For how Imbi combines the roles of a
user who is a member of many organizations, see
[Permissions across organizations](roles-and-permissions.md#permissions-across-organizations).

The `organization:create`, `organization:read`, `organization:update`, and
`organization:delete` permissions control the organization API.

## Users

A user account has these fields:

| Field | What it is |
|---|---|
| Email | The sign-in name. Imbi also sends notifications to it |
| Display name | The name that the UI shows |
| Account type | **Regular user** or **Administrator**. See [Platform administrators](#platform-administrators) |
| Account active | An inactive account cannot sign in or use the API |
| Email notifications | Send notifications by email |
| Memberships | The organizations of the user, and the role in each |

### How Imbi creates users

Imbi creates users in three ways:

1. **Initial setup.** `imbi-api setup` creates the first user. This user
   is a platform administrator, with the `admin` role in the `default`
   organization.
2. **Manual creation.** A platform administrator creates the user from
   **Admin > Global Admin > User Management**.
3. **First sign-in with a login provider.** When a person signs in with a
   login provider for the first time, Imbi creates the user. To stop this,
   set `IMBI_AUTH_OAUTH_AUTO_CREATE_USERS=false`.

When a user without a membership signs in, Imbi adds the user to an
organization with the `default` role. If there is only one organization,
Imbi uses it. If there are more, Imbi uses the organization with the slug
`default`.

### Create a user

1. Open **Admin > Global Admin > User Management**.
2. Click **New User**.
3. Enter the display name and the email.
4. Select the account type.
5. Under **Membership**, select an organization and a role. A user without
   a membership has no permissions.
6. If local passwords are enabled, enter a password.
7. Click **Create User**.

Imbi does not send an invitation. Give the password to the user, or tell
the user to sign in with a login provider. A user without a password can
sign in only with a login provider.

### Change a user

1. Open **Admin > Global Admin > User Management**.
2. Click the user.
3. Click **Edit User**.
4. Change the fields. Under **Memberships**, select the organizations of
   the user and select a role for each.
5. Click **Save Changes**.

You can also add a membership from the user page. Under
**Organization Memberships**, click **Add to Organization**.

### Deactivate a user

In the user list, click the **Active** badge of the user. The badge changes
to **Inactive**. The user cannot sign in or use the API. Imbi keeps the
data and the history of the user. To activate the user again, click the
badge again.

### Platform administrators

A platform administrator is a user with **Account type** set to
**Administrator** (`is_admin` in the API). This is not the same as the
`admin` role.

| | Platform administrator (`is_admin`) | `admin` role |
|---|---|---|
| Where you set it | On the user account | On a membership in one organization |
| Scope | The full installation | One organization |
| Permission checks | Passes every permission check | Has every permission in its organization |
| **Admin** menu in the UI | Shows | Does not show |
| Membership | Still necessary for the agents, agent tasks, workflows, and secrets of an organization | Is a membership |
| Service accounts | Cannot be one | Can have it |

Only a platform administrator can make a user a platform administrator, or
change a platform administrator. Only a platform administrator can change
runner pools.

## Teams

A team is a group of users in one organization. Teams do not give
permissions. Use teams for ownership:

- Each project has an owner team.
- Each agent has an owner team. See [Agents](agents.md).
- Each workflow has an owner team. A workflow trigger can let only the
  members of the owner team start the workflow. See
  [Workflows](workflows.md).
- An AI model can be limited to some teams. See [AI Models](ai-models.md).

The `team:create`, `team:read`, `team:update`, and `team:delete`
permissions control the team API. `team:update` also lets you add and
remove members.

### Create a team

1. In the top bar, select the organization.
2. Open **Admin > &lt;Org&gt; Admin > Teams**. &lt;Org&gt; is the name of the
   organization that you selected.
3. Click **New Team**.
4. Complete the form.
5. Click **Create Team**.

### Change the members of a team

1. Open **Admin > &lt;Org&gt; Admin > Teams**.
2. Click the team.
3. Under **Team Members**, click **Add Member**.
4. Enter the email of the user.
5. Click **Add**.

To remove a member, click the remove button on the row of the member.

## Service accounts

A service account is a principal for a machine, not for a person. Like a
user, a service account gets permissions from its role in each
organization that it is a member of. A service account is never a platform
administrator.

To manage service accounts, their API keys, and their client credentials,
open **Admin > Global Admin > Service Accounts**. Imbi also creates a
service account for each agent. See [Agents](agents.md).
