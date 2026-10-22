# PagerDuty

The `pagerduty` plugin keeps one PagerDuty service for each Imbi project.
It routes the service to the escalation policy of the owning team, keeps
the service dependencies the same as the Imbi project dependencies, and
shows the service incidents on the project **Incidents** tab.

## Capabilities

| Capability | Label | Default | Scope |
|---|---|---|---|
| `lifecycle` | Service lifecycle | On | Project-scoped |
| `incidents` | Incidents | On | Project-scoped |
| `webhook-actions` | Webhook actions | On | Project-scoped. Has no actions |
| `analysis` | Project doctor | On | Project-scoped |

## Configuration

### Options

| Option | Label | Required | Meaning |
|---|---|---|---|
| `team_escalation_policy_mapping` | Team to escalation policy | Yes | A map from an Imbi team slug to a PagerDuty escalation policy ID |
| `default_escalation_policy_id` | Default escalation policy id | No | The escalation policy for a team that has no entry in the map |
| `gateway_webhook_url` | Gateway webhook URL | No | The public imbi-gateway delivery URL of a PagerDuty webhook in Imbi. When set, Imbi makes a webhook subscription for each new service. Leave it empty to make no subscriptions |

To get a value for `gateway_webhook_url`, make a webhook for this
integration at **Admin > *Organization* Admin > Webhooks**. Then copy the
**Delivery URL** from the `webhook-actions` capability on the integration
page. See [Webhooks](../admin/webhooks.md).

### Credentials

| Credential | Required | Secret | Meaning |
|---|---|---|---|
| `api_key` | Yes | Yes | A PagerDuty REST API key with write access to services |

PagerDuty is a cloud service. The plugin always calls
`https://api.pagerduty.com`.

## Escalation policy

The plugin selects the escalation policy of a project in this order:

1. The entry for the owning team in `team_escalation_policy_mapping`.
2. `default_escalation_policy_id`.

A PagerDuty service must have an escalation policy. If the plugin finds no
policy, it does not create the service and gives a message that names the
team.

When a project moves to a different team, the plugin changes the
escalation policy of the service. If the new team maps to the same policy,
it changes nothing.

## Service dependencies

An Imbi dependency `A depends on B` becomes a PagerDuty technical service
dependency. The service of A is the dependent service. The service of B is
the supporting service. The plugin examines the dependencies in both
directions for each project.

The plugin removes a PagerDuty dependency only when both of these are
true:

- The service on the other side is linked to an Imbi project.
- Imbi has no dependency between the two projects.

The plugin does not change dependencies on services that Imbi does not
manage, or on business services. When a dependent project has no
PagerDuty service, the plugin skips it and names it in the Doctor finding.

## Lifecycle

| Imbi event | What the plugin does |
|---|---|
| Project created | Finds a service with the same name as the project slug. If one exists, links it. If none exists, creates a service with the project slug as the name, the project description, and the team escalation policy. Then makes the webhook subscription, if `gateway_webhook_url` is set |
| Project updated | Sets the service name to the project slug and updates the description. If no service exists, creates it |
| Project relocated | Changes the escalation policy when the team policy changes |
| Dependencies changed | Syncs the service dependencies |
| Project deleted | Deletes the webhook subscriptions of the service, then deletes the service. This happens only when **Also delete the associated repository** is selected in the delete dialog |
| Project archived | Nothing. PagerDuty has no archive state |

The plugin finds the service of a project from the `pagerduty-service`
project link. If there is no link, it searches by the project slug, then
by the previous slug.

The webhook subscription sends these events: `incident.triggered`,
`incident.acknowledged`, `incident.resolved`, `incident.escalated`, and
`incident.reopened`. PagerDuty returns the signing secret of a
subscription only once. Imbi encrypts it and stores it on the
`EXISTS_IN` edge. imbi-gateway uses it to verify the signature of each
delivery.

## Incidents

The **Incidents** tab asks PagerDuty for the incidents of the project
service since the selected start time. It can filter by status.

## Webhook actions

None. The capability has no actions. imbi-gateway records PagerDuty
deliveries as events.

## Doctor checks

| Finding | Result | Fix |
|---|---|---|
| `escalation-policy` | Pass: the team maps to a policy. Warn: no policy for the team | None |
| `exists-in` | Fail: no edge and no service with the project slug. Warn: no edge, but a service with that name exists | **Create / link the PagerDuty service**, or **Repair the PagerDuty service link** |
| `service` | Pass: the service exists. Fail: PagerDuty returns `404` for the service on the edge. Warn: PagerDuty cannot be reached | **Create / link the PagerDuty service** |
| `canonical-url` | Fail: the API URL on the edge is not `https://api.pagerduty.com/services/<id>` | **Repair the PagerDuty service link** |
| `dashboard-link` | Fail or warn: the `pagerduty-service` link is not the service web URL | **Repair the PagerDuty service link** |
| `service-escalation-policy` | Fail: the service uses a different policy than the team maps to | **Repoint the escalation policy** |
| `service-dependencies` | Fail: the PagerDuty dependencies are different from Imbi. Warn: a dependent project has no PagerDuty service | **Sync PagerDuty service dependencies** |

The fixes:

- **Create / link the PagerDuty service** searches for a service with the
  project slug as the name. If it finds none, it creates one, the same as
  the lifecycle create. You must confirm it.
- **Repair the PagerDuty service link** links a service that exists. It
  never creates one.
- **Repoint the escalation policy** and **Sync PagerDuty service
  dependencies** are *sweepable*. They change only routing and
  dependencies, and never create or delete a service.

### Fix all projects

Two operations in **Admin > Maintenance** apply fixes to all projects:

- **Apply Sync Fixes** runs the Doctor for each project. Then it applies
  only the sweepable fixes: the escalation policy and the dependencies.
- **Remediate Findings** applies every fix in the stored Doctor report,
  including **Create / link the PagerDuty service**. It can create
  services.

## Known limits

- The service name is the project slug. A service with a different name
  is not found by name.
- The plugin finds the subscriptions of a service by listing all
  subscriptions. The PagerDuty API has no filter for this.
- The dependency sync reads the dependencies of a service in one request,
  with no pages.
- The dependency sync and the subscription secret were written against
  the PagerDuty API documentation. They were not verified against a live
  PagerDuty account.
