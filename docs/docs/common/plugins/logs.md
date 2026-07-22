# Logs Capability

`LogsCapability` is the contract base for log-search integrations. Bind
it with a `Capability(kind='logs', handler=...)` in the plugin's
manifest. Required methods are `search` and `schema`; histogram support
is optional via `histogram()` plus the `supports_histogram` hint on the
capability.

Surfaces: **ui, api**.

See [Authoring Plugins](index.md) for the manifest, capabilities,
context, credential decryption, and error conventions shared by every
plugin.

```python
import typing

from imbi_common.plugins import (
    LogHistogramBucket,
    LogQuery,
    LogResult,
    LogsCapability,
    PluginContext,
)


class LokiLogs(LogsCapability):
    async def search(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        query: LogQuery,
    ) -> LogResult:
        ...

    async def schema(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
    ) -> list[dict[str, typing.Any]]:
        ...

    async def histogram(
        self,
        ctx: PluginContext,
        credentials: dict[str, str],
        query: LogQuery,
        bucket_count: int = 60,
    ) -> list[LogHistogramBucket]:
        ...
```

## Method contracts

- **`search`** — return a `LogResult` with `entries` ordered most-recent
  first. Honor `query.limit` and `query.cursor`. When more results are
  available, populate `next_cursor` with an opaque token the upstream
  system can decode on the next call. If a cursor has expired or become
  invalid, raise
  [`CursorExpiredError`][imbi_common.plugins.CursorExpiredError]
  rather than silently returning empty results.
- **`schema`** — return a list of field descriptors. The shape is
  intentionally loose so capabilities can surface vendor-specific
  metadata; at minimum include a `name` and a human-readable `label` for
  each field exposed to filters.
- **`histogram`** — optional. Implement this method and set the
  `supports_histogram` hint to enable the histogram panel in the host UI.
  Return one `LogHistogramBucket` per time bucket spanning the query's
  time range. The base implementation returns an empty list; the host
  checks the hint before calling it.

## Queries and filters

`LogQuery.filters` are `(field, op, value)` triples with five operators
(`eq`, `ne`, `contains`, `starts_with`, `regex`). `LogQuery.levels`
optionally restricts results to a set of canonical level names (e.g.
`['ERROR', 'WARN']`); an empty list means no level filter. Translate
both into the upstream provider's query language; raise a
domain-appropriate exception if a filter cannot be satisfied so the host
can surface a clear error.

## Hints

- **`supports_histogram`** — the capability implements `histogram()`.
- **`cacheable`** — the host may cache reads from this capability.

## API reference

::: imbi_common.plugins.LogsCapability

::: imbi_common.plugins.LogQuery

::: imbi_common.plugins.LogFilter

::: imbi_common.plugins.LogEntry

::: imbi_common.plugins.LogResult

::: imbi_common.plugins.LogHistogramBucket
