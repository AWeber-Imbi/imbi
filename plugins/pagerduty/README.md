# imbi-plugin-pagerduty

The PagerDuty plugin for the [Imbi](https://github.com/AWeber-Imbi)
platform, distributed as a single Python package (`imbi_plugin_pagerduty`)
exposing one Integration (`pagerduty`) with four capabilities:

- **`lifecycle`** — provisions and maintains a PagerDuty *service* for
  each project, routed to the owning team's escalation policy (via the
  `team_escalation_policy_mapping` integration option), and a per-service
  V3 webhook subscription back to Imbi. When a project dependency is
  added or removed in Imbi, it syncs the PagerDuty service dependencies.
- **`incidents`** — live-queries PagerDuty for the incidents on a
  project's service for the project-detail Incidents tab.
- **`webhook-actions`** — receives PagerDuty incident webhooks. v1 records
  events through the gateway and advertises no custom actions.
- **`analysis`** — the Project Doctor. It checks the service link, the
  service's escalation policy against the team mapping, and the service
  dependencies against Imbi's `DEPENDS_ON` edges. Each problem it can
  repair has a Fix button.

### Service dependencies

An Imbi `A DEPENDS_ON B` edge becomes a PagerDuty technical-service
dependency: A's service is the dependent service, and B's service is the
supporting service. Imbi removes a PagerDuty dependency only when both
services are linked to Imbi projects and Imbi has no `DEPENDS_ON` edge
between them. Dependencies on services that Imbi does not manage, and on
business services, stay as they are. A neighbour project with no
PagerDuty service is reported and skipped.

### Bulk repair

The **Apply Sync Fixes** maintenance operation (Admin → Maintenance) runs
the Doctor for every project, then applies only the fixes marked
sweepable: the escalation-policy repoint and the dependency sync. It
never creates or deletes a PagerDuty service.

The Imbi host discovers the package by the `imbi_plugin_*` naming
convention and reads the module-level `PLUGIN` attribute; there are no
entry points. All plugin base classes come from `imbi_common.plugins`.

## Development

```bash
moon run root:setup     # uv sync + pre-commit hooks
moon run pagerduty:test # coverage (fails under 85%)
moon run pagerduty:lint pagerduty:typecheck pagerduty:format   # ruff + basedpyright + format check
```

Authentication is a PagerDuty REST API key (`auth_type='api_token'`),
configured as an encrypted plugin credential. PagerDuty is cloud-only, so
there is no host-flavor routing.
