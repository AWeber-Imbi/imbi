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
missing SonarQube projects.

A typical webhook rule:

```
Handler: sonarqube#update_project_from_webhook
Filter:  /branch/is_main==true
Config:  [
           {"metric": "coverage", "path": "/test_coverage"},
           {"metric": "ncloc",    "path": "/lines_of_code"}
         ]
```
