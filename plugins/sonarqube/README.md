# imbi-plugin-sonarqube

SonarQube webhook-action plugin for Imbi.

The plugin registers a `sonarqube` entry in the Imbi plugin registry
(plugin type: `webhook`). When a SonarQube webhook arrives at
`imbi-gateway` and a matching `WebhookRule` dispatches to
`imbi_plugin_sonarqube.actions.update_project_from_webhook`, the
handler:

1. Reads the metric→JSONPointer mapping from `WebhookRule.handler_config`.
2. Fetches `/api/measures/component` from SonarQube using the plugin's
   stored API token and the `ThirdPartyService.api_endpoint`.
3. Patches the matched Imbi project's facts.

## Configuration

Operators attach a `sonarqube` plugin instance to the SonarQube
`ThirdPartyService` and store the SonarQube API token in the plugin's
encrypted credentials.

A typical webhook rule:

```
Handler: imbi_plugin_sonarqube.actions.update_project_from_webhook
Filter:  /branch/is_main==true
Config:  [
           {"metric": "coverage", "path": "/test_coverage"},
           {"metric": "ncloc",    "path": "/lines_of_code"}
         ]
```
