# imbi-plugin-sonarqube

SonarQube integration plugin for Imbi (Plugin Architecture v3).

The package ships a single `SonarQubePlugin` (slug `sonarqube`), discovered
by the imbi-common registry's `imbi_plugin_*` convention scan via the
module-level `PLUGIN` attribute. Its manifest declares:

- a `service_url` integration-level option (the SonarQube base URL),
- an `api_token` credential (the integration's only credential) holding a
  SonarQube **user** token, and
- one `webhook-actions` capability cataloging the
  `update_project_from_webhook` action.

When a SonarQube webhook arrives at `imbi-gateway` and a matching
`WebhookRule` dispatches to `sonarqube#update_project_from_webhook`, the
handler:

1. Reads the metric→JSONPointer mapping from `WebhookRule.handler_config`.
2. Fetches `/api/measures/component` from SonarQube using the Integration's
   decrypted `api_token` credential and its `service_url` option.
3. Patches the matched Imbi project's facts.

## Configuration

Operators create a SonarQube Integration, set its `service_url` option, and
store the SonarQube API token in the Integration's encrypted credentials.

The `api_token` **must be a user token** — created under *My Account >
Security* in SonarQube and prefixed `squ_`. SonarQube's analysis tokens,
`sqa_` (global) and `sqp_` (project), are restricted to the endpoints a
scanner uses and answer `403` to every request this plugin makes, including
`/api/measures/component` and the Project Doctor's component lookup. The
restriction rides on the token *type*, so issuing an analysis token from an
administrator account does not help. Grant the token's account Browse on the
projects being read, plus Create Projects if the Project Doctor should create
missing SonarQube projects and Administer on a project whose main branch it
should switch.

## Project Doctor

The `analysis` capability checks three things, offering a fix for the
first two:

1. **The `EXISTS_IN` edge** — that the component key
   (`<team-slug>:<project-slug>`, or the edge's own identifier) exists in
   SonarQube, and that the edge's canonical URL and `sonarqube` dashboard link
   match it. The fix searches for the component, creates it when absent, and
   writes the edge.
2. **The main branch** (`main-branch`) — SonarQube reports a project's state
   from the single branch flagged `isMain`, so a repository that moved from
   `master` to `main` keeps syncing measures from an analysis that stopped
   running. When `/api/project_branches/list` shows the expected branch and it
   is *not* the main branch, the finding fails and the fix `POST`s
   `/api/project_branches/set_main`.
3. **The main branch is missing** (`main-branch-missing`) — when SonarQube has
   no such branch at all, the finding fails with **no** fix offered: SonarQube
   only records a branch once an analysis has run on it, so nothing this plugin
   can call will create one. Either CI needs to analyze that branch, or the
   project genuinely uses a different one and `main_branch` should say so.

The expected branch is the capability's `main_branch` option, defaulting to
`main`. Set it on the Integration's *Project doctor* capability for the
org-wide convention; because the host layers capability options
(Integration < project-type `USES` edge < project `USES` edge), a project
type or single project whose trunk is named something else can override it
without changing the default.

A typical webhook rule:

```
Handler: sonarqube#update_project_from_webhook
Filter:  /branch/is_main==true
Config:  [
           {"metric": "coverage", "path": "/test_coverage"},
           {"metric": "ncloc",    "path": "/lines_of_code"}
         ]
```
