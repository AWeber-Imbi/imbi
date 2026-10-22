# Plugins

These plugins ship with Imbi. Each page tells you what the plugin does,
how to configure an integration of it, and what its Doctor checks.

| Plugin | Slug | What it does |
|---|---|---|
| [AWS](aws.md) | `aws` | IAM Identity Center sign-in, CloudWatch Logs search, and SSM Parameter Store configuration |
| [GitHub](github.md) | `github` | Identity, deployments, repository lifecycle, commit and pull request sync, and repository Doctor checks |
| [Google](google.md) | `google` | Sign in with a Google or Google Workspace account |
| [Logz.io](logzio.md) | `logzio` | Log search on the project **Logs** tab |
| [OIDC](oidc.md) | `oidc` | Sign in with any OpenID Connect provider |
| [PagerDuty](pagerduty.md) | `pagerduty` | One PagerDuty service for each project, incidents, escalation policy, and service dependency sync |
| [SonarQube](sonarqube.md) | `sonarqube` | Project facts from SonarQube measures, and component Doctor checks |

To enable a plugin and add an integration, see
[Integrations and Plugins](../admin/integrations-and-plugins.md). To write
a plugin, see [Authoring Plugins](../common/plugins/index.md).
