# imbi-plugin-pagerduty

The PagerDuty plugin for the [Imbi](https://github.com/AWeber-Imbi)
platform, distributed as a single Python package (`imbi_plugin_pagerduty`)
exposing one Integration (`pagerduty`) with three capabilities:

- **`lifecycle`** — provisions and maintains a PagerDuty *service* for
  each project, routed to the owning team's escalation policy (via the
  `team_escalation_policy_mapping` integration option), and a per-service
  V3 webhook subscription back to Imbi.
- **`incidents`** — live-queries PagerDuty for the incidents on a
  project's service for the project-detail Incidents tab.
- **`webhook-actions`** — receives PagerDuty incident webhooks. v1 records
  events through the gateway and advertises no custom actions.

The Imbi host discovers the package by the `imbi_plugin_*` naming
convention and reads the module-level `PLUGIN` attribute; there are no
entry points. All plugin base classes come from `imbi_common.plugins`.

## Development

```bash
just setup   # uv sync + pre-commit hooks
just test    # coverage (fails under 85%)
just lint    # ruff, ruff-format, basedpyright
```

Authentication is a PagerDuty REST API key (`auth_type='api_token'`),
configured as an encrypted plugin credential. PagerDuty is cloud-only, so
there is no host-flavor routing.
