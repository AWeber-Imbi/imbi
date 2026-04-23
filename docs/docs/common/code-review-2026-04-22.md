# Code Review Findings & Remediation Plan — 2026-04-22

Scope: `src/imbi_common/` (graph, clickhouse, auth, blueprints, models, settings,
server, versioning, lifespan). Findings are grouped by risk and ordered to make
parallel subagent dispatch straightforward — each task lists its files, fix
approach, verification, and whether it can run independently.

---

## Tranche A — Bug fixes (dispatch first, each independent)

### A1. ClickHouse insert ignores field aliases

- **Problem:** `clickhouse.insert()` builds `column_names` and row values via
  `model.model_dump()` (no `by_alias=True`). `OperationLog.row_version` has
  `alias='_row_version'`, and the `operations_log` table column is
  `_row_version`. Current insert path mis-names the column and will fail (or
  insert into the wrong column).
- **Files:** `src/imbi_common/clickhouse/__init__.py:138,142`
- **Fix:** Switch both dumps to `model_dump(by_alias=True)`. Dump each model
  once (see A7) and reuse the keys from the first row.
- **Verification:**
  - Add a test that inserts an `OperationLog` against a fake/stub driver and
    asserts `column_names` contains `_row_version`.
  - `just test tests/clickhouse/`.
- **Depends on:** none.

### A2. Orphan `_dump` / `_dumps` / `_process_nested_dicts` in clickhouse package

- **Problem:** `_dump`, `_dumps`, `_process_nested_dicts` are defined and
  tested, but the `insert()` path does not call them. Any model with a
  `list[BaseModel]` field (intended for ClickHouse `Nested` columns) is
  silently serialized as a list of dicts.
- **Files:** `src/imbi_common/clickhouse/__init__.py:20-94,112-144`; tests in
  `tests/clickhouse/test_init.py`.
- **Fix:** Decide with the maintainer which path is real. Two options:
  1. Wire `_dump` into `insert()` (preferred — keeps nested flattening for
     ClickHouse `Nested` columns). Combine with A1.
  2. Delete `_dump`, `_dumps`, `_process_nested_dicts`, and their tests.
- **Verification:** If option 1: extend `test_init.py` with a model that has
  a `list[BaseModel]` field and assert column names include
  `field.subfield` keys. If option 2: ensure tests still pass after removal.
- **Depends on:** coordinate with A1 (same file, overlapping diff).

### A3. `Graph.search_nodes` bypasses `model_validate`

- **Problem:** `search_nodes` goes straight to `model_construct`, skipping
  validators. Compare to `Graph.match` (`graph/client.py:242-251`) which
  tries `model_validate` first and only falls back to `model_construct` on
  `ValidationError`. Result: fields like `created_at` stay as ISO strings
  instead of `datetime`, `icon` stays as `str` instead of `HttpUrl`, etc.
- **Files:** `src/imbi_common/graph/client.py:393-404`
- **Fix:** Mirror the try/except pattern from `match()`. Extract the shared
  logic into a small helper (e.g. `_row_to_model(node_type, props)`) and
  call from both sites.
- **Verification:** Add a test that round-trips a `Project` through
  `search_nodes` and asserts `isinstance(result.created_at, datetime)`.
- **Depends on:** none.

### A4. `_is_list_edge` has dead `Annotated` branch

- **Problem:** In pydantic v2, `FieldInfo.annotation` is the unwrapped type;
  metadata lives on `FieldInfo.metadata`. `typing.get_origin(annotation) is
  typing.Annotated` is never true. Verified empirically on `Project`.
- **Files:** `src/imbi_common/graph/cypher.py:58-70`
- **Fix:** Collapse to a single `return typing.get_origin(
  field_info.annotation) is list`.
- **Verification:** `tests/test_cypher.py` — keep existing tests green; no
  new cases needed (they already cover `Annotated[list[...], Edge]` via
  `Project.project_types`).
- **Depends on:** none.

### A5. `Clickhouse._connect` sleeps on final failed attempt + recursion

- **Problem:** `client.py:181-194` sleeps *before* the
  `attempt >= max_connect_attempts` check, so the last failed attempt still
  waits. Also recursive rather than iterative (`max_connect_attempts`-deep
  stack, exponential backoff doubling each level).
- **Files:** `src/imbi_common/clickhouse/client.py:151-194`
- **Fix:** Rewrite as a `for attempt in range(1, max+1):` loop. Only sleep
  between attempts, not after the last one. Use `async with asyncio.sleep`
  or just `await asyncio.sleep(...)` inside the loop.
- **Verification:** Add a unit test with a patched
  `clickhouse_connect.driver.create_async_client` that always raises
  `OperationalError` and assert the number of sleeps == `max - 1`.
- **Depends on:** none.

### A6. `auth.encryption.get_fernet` mutates shared settings

- **Problem:** `get_fernet()` re-generates and writes a new `encryption_key`
  back into the passed-in `auth_settings`. Its comment already calls out
  that this branch "should not happen" since `Auth` auto-generates. The
  mutation affects the shared singleton returned by `get_auth_settings()`.
- **Files:** `src/imbi_common/auth/encryption.py:170-177`
- **Fix:** Remove the auto-generate branch. If `encryption_key` is unset,
  raise `RuntimeError('Encryption key not configured')` (mirrors
  `TokenEncryption.get_instance`).
- **Verification:** `just test tests/auth/`.
- **Depends on:** none.

### A7. `insert()` dumps each model twice

- **Problem:** `model_dump()` is called on `data[0]` for column names, then
  again on every `model` for values. For N rows: N+1 dumps where N-1 is
  wasted.
- **Files:** `src/imbi_common/clickhouse/__init__.py:138-144`
- **Fix:** Dump once per model, collect into a list of dicts, take
  `list(dumps[0].keys())` for columns and
  `[list(d.values()) for d in dumps]` for rows.
- **Verification:** Existing tests must still pass.
- **Depends on:** **must** land after A1 (same lines, same function).

---

## Tranche B — DRY cleanups (independent, mechanical)

### B1. Collapse `create_access_token` / `create_refresh_token`

- **Files:** `src/imbi_common/auth/core.py:12-91`
- **Fix:** Introduce private `_create_token(subject, *, token_type,
  ttl_seconds, extra_claims, auth_settings)`. Keep the two public wrappers
  as thin passthroughs for API stability.
- **Verification:** `just test tests/auth/test_core.py`.

### B2. Unify the three `_delete_*` helpers in `Graph`

- **Files:** `src/imbi_common/graph/client.py:518-571`
- **Fix:** Single `_delete_embeddings_where(conn, *, node_label, node_id,
  attribute=None, model_name=None, min_chunk_index=None)` that composes a
  `DELETE FROM public.embeddings WHERE ...` via `psycopg.sql`. Three call
  sites collapse to kwargs. Also standardize on `%(name)s` placeholders
  (currently a mix of named and positional).
- **Verification:** `just test tests/test_graph.py` plus an integration
  test for the three historical call sites.

### B3. Extract `BELONGS_TO` edge annotation

- **Files:** `src/imbi_common/models.py` (Team, Environment, ProjectType,
  ThirdPartyService, LinkDefinition — each defines the same `Organization`
  edge).
- **Fix:** Module-level `BelongsToOrganization = typing.Annotated[
  Organization, Edge(rel_type='BELONGS_TO', direction='OUTGOING')]`. Reuse.
- **Verification:** `just test tests/test_models.py`.

### B4. Deduplicate enum detection in blueprints

- **Files:** `src/imbi_common/blueprints.py:37-45,116-122`
- **Fix:** Have `_map_string_type` return `(field_type, enum_values)` where
  `enum_values` is `None` for non-enum string types. `apply_blueprints`
  uses the tuple to decide whether to wrap in `BeforeValidator` — no second
  shape-check needed.
- **Verification:** `just test tests/test_blueprints.py`.

### B5. DRY Clickhouse `query`/`insert` error handling

- **Files:** `src/imbi_common/clickhouse/client.py:105-113,136-144`
- **Fix:** Extract a `@contextlib.contextmanager` or decorator
  `_translate_errors(operation: str)` that logs, captures to Sentry when
  available, and re-raises as `DatabaseError`. Use it to wrap the `await
  self._clickhouse.insert(...)` / `.query(...)` call sites.
- **Verification:** Existing tests plus a new one that asserts the
  decorator calls `sentry_sdk.capture_exception` when available.

### B6. `merge()` default `match_on` duplicates `_identity()`

- **Files:** `src/imbi_common/graph/cypher.py:130-141,265-269`
- **Fix:** `merge()` should call `_identity(node)` for the default rather
  than re-checking `isinstance(node, Node)`.
- **Verification:** `just test tests/test_cypher.py`.

---

## Tranche C — Performance (measure before optimizing)

### C1. Cache per-class edge / embeddable descriptors

- **Files:** `src/imbi_common/graph/cypher.py:_edge_fields`;
  `src/imbi_common/graph/client.py:_embeddable_fields`,
  `_strip_edge_fields`.
- **Motivation:** Every CRUD call walks `model_fields.items()` and inspects
  metadata. For the hot path this is wasteful. Caveat: only worth doing if
  profiling shows it matters.
- **Fix:** `@functools.cache` (or a module-level `dict[type, ...]`) keyed
  by the model class. Return tuples, not lists, so the cached value is
  immutable.
- **Verification:** Existing tests + a micro-benchmark in a throwaway
  script to confirm improvement. Do **not** commit the benchmark.

### C2. `_build_cypher_sql` round-trip through `as_string`

- **Files:** `src/imbi_common/graph/client.py:658-672`
- **Motivation:** Currently: `sql.SQL(template).format(...)` → `.as_string(
  conn)` → `sql.SQL(resolved)` → outer `.format(...)`. The round-trip both
  costs CPU and creates a brace-injection footgun (if the resolved string
  contains stray `{` / `}` they must be escaped).
- **Fix:** Compose directly via `sql.Composed([...])` and skip the string
  round-trip. Keep the dollar-quote tag selection.
- **Verification:** Full `tests/test_graph.py`; manual check with a value
  containing literal braces.

### C3. Embeddings resolver trims redundant lock acquisitions

- **Files:** `src/imbi_common/graph/embeddings.py:25-46`
- **Motivation:** `aembed_one` → `_resolve` → `default_model` →
  `_get_registry` takes the RLock twice for every embed call.
- **Fix:** Cache `_default_model` at module scope after first load and
  short-circuit `default_model()` when it's non-None.
- **Verification:** `just test tests/test_embeddings.py`.

---

## Tranche D — Minor / nice-to-have

- **D1.** Remove redundant `import logging` + local `logger = logging.getLogger(__name__)` inside `Auth.generate_encryption_key_if_missing` — use module-level `LOGGER`. `src/imbi_common/settings.py:74-76`.
- **D2.** `Clickhouse.query` row-zip uses `strict=False`; switch to `strict=True` so a driver mismatch raises instead of truncating. `src/imbi_common/clickhouse/client.py:147`.
- **D3.** `blueprints.get_edge_model` uses `type(...)` to build a pydantic subclass; swap to `pydantic.create_model` for idiomatic metaclass handling. `src/imbi_common/blueprints.py:266-270`.
- **D4.** Add a unit test for `_cypher_param` string escaping with values like `O'Brien\back` and embedded `$$`. `src/imbi_common/graph/client.py:605-628`.
- **D5.** `_execute_batch` toggles autocommit manually; consider `async with conn.transaction():` so rollback exceptions don't mask the original error. `src/imbi_common/graph/client.py:589-603`. (Verify against the deployed AGE version before changing.)

---

## Dispatch plan

One subagent per tranche entry is the cleanest split. Safe parallel groups:

- **Group 1 (parallel):** A3, A4, A5, A6, B1, B3, B4, B6, D1, D2, D3, D4.
- **Group 2 (serial, same file):** A1 → A7 → A2 (all touch
  `clickhouse/__init__.py:insert`; keep them on one agent or chain them).
- **Group 3 (parallel, after Group 1):** B2, B5, C1, C2, C3, D5.

Every task must end with `just lint` + the relevant `just test <file>`
target green before handing back. For anything that touches the ClickHouse
or Postgres/AGE runtime paths (`A1`, `A2`, `A5`, `B2`, `B5`, `C2`, `D5`),
the agent should run `just test` with the Docker stack up, not just the
narrow file target.
