# Configuration
The Sentry automations are configured in the Imbi configuration file in the `automations/sentry`
section using the following keys:

* **project_link_type_id** optional Imbi identifier for the project link type created for Sentry links.
  If this value is unspecified, then the automation will not create a project link to the Sentry
  dashboard.
* **auth_token** the Sentry authorization token used to create projects in sentry.  It needs the
  following scopes -- `event:admin`, `event:read`, `member:read`, `org:read`, `project:read`,
  `project:releases`, `team:read`, `event:write`, `project:write`, `project:admin`
* **orgranization** the Sentry organization to create teams under.  This automation only supports a
  single organization today.
* **url** an optional URL to the Sentry instance.  This defaults to ``https://sentry.io/``

If the `auth_token` and `organization` are set in the configuration file then the sentry automation
will be enabled in the `/ui/settings` response which, in turn, enables the functionality in the
frontend.

# Sentry keys
When a project is created in Sentry, the automation retrieves the public and private (deprecated)
client DSNs and stores them as secrets in the `v1.project_secrets` table.  These are available from
the API as `/projects/{id}/secrets`.
