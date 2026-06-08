# Incidents Plugins

`IncidentsPlugin` is the abstract base for incident-management
integrations (e.g. PagerDuty). Declare `plugin_type='incidents'` in the
manifest. The single required method is `list_incidents`. Like the logs
tab, the source system stays authoritative — incidents are live-queried
on demand and the host keeps no local incident store, so the resulting
project-detail Incidents tab is read-only.

See [Authoring Plugins](index.md) for the manifest, context, credential
resolution, and error conventions shared by every plugin.

```python
import datetime

from imbi_common.plugins import (
    IncidentResult,
    IncidentsPlugin,
    PluginContext,
)


class PagerDutyIncidentsPlugin(IncidentsPlugin):
    manifest = manifest  # plugin_type='incidents'

    async def list_incidents(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        *,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
        statuses: list[str] | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> IncidentResult:
        ...
```

## Method contracts

- **`list_incidents`** — resolve the project's remote service (typically
  from a project link populated by a companion lifecycle plugin) and
  return an `IncidentResult` whose `incidents` are ordered most-recent
  first. Honor the `start_time`/`end_time` window, the optional
  `statuses` filter, and `limit`. When more results are available,
  populate `next_cursor` with an opaque token the upstream system can
  decode on the next call; raise
  [`CursorExpiredError`][imbi_common.plugins.CursorExpiredError] if a
  cursor is no longer valid. Set `total` only when the source reports a
  count cheaply — live-query sources that would need a full scan should
  leave it `None`. When the project has no resolvable remote service,
  return an empty `IncidentResult` rather than raising.

## Result shape

`IncidentView` is the per-incident row rendered in the tab. `urgency`,
`resolved_at`, and `service` are optional because not every source
populates them (e.g. an unresolved incident has no `resolved_at`, and
some payloads omit `urgency`); `id`, `title`, `status`, `created_at`,
and `url` are always required so the tab can render and deep-link every
row.

## API reference

::: imbi_common.plugins.IncidentsPlugin

::: imbi_common.plugins.IncidentView

::: imbi_common.plugins.IncidentResult
