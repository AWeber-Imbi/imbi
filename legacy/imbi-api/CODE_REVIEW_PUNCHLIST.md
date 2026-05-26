# Imbi API — Code Review Punch List

Findings from an in-depth review covering auth/security, the large endpoint files,
bootstrap/lifespans/shared modules, plugins/identity/scoring, and the remaining
endpoints + tests. Each item is actionable; check off as resolved.

Severity legend: **C** Critical · **H** High · **M** Medium · **L** Low

---

## Critical

- [x] **C1.** Fix Python-2 `except` clauses in `src/imbi_api/endpoints/auth_providers.py:46` and `src/imbi_api/domain/models.py:1159` (`except (json.JSONDecodeError, TypeError):`). _(Note: Python 3.14 parses the unparenthesized form as a tuple, so it isn't a hard SyntaxError, but the explicit tuple is intent-preserving.)_ — landed on `main` (6c9a365).
- [ ] **C2.** OAuth callback returns tokens in URL fragment to caller-supplied `redirect_uri` — `src/imbi_api/endpoints/auth.py:704, 967-976, 1090-1098`. Enforce a redirect-URI allow-list and move the refresh token to an `HttpOnly; Secure; SameSite=Strict` cookie.
- [~] **C3.** Identity callback has no auth dependency — `src/imbi_api/identity/endpoints.py:191-222`. Add `Depends(require_auth)`, assert `auth.user.id == state.actor_user_id`, and add a nonce-replay cache (`src/imbi_api/identity/flows.py:230-237`). Nonce-replay cache landed in PR #341. The `require_auth` half does not fit the Bearer-token architecture (cross-origin IdP redirect strips `Authorization`); would need a cookie session — separate architectural change.
- [x] **C4.** Plugin reload is unauthenticated arbitrary code execution — `src/imbi_api/plugins/reload.py:31-43` + `src/imbi_api/plugins/installer.py:24-57`. Installer hardening (`^imbi-plugin-[a-z0-9_-]+$` allowlist, pinned `--index-url`, `--no-deps`) already landed. Plugin reload pub/sub payloads are now HMAC-SHA256 signed with a key derived from `jwt_secret` (ts:nonce:sig format, 5-minute window); subscriber rejects unsigned/stale/invalid payloads. — PR #348.
- [~] **C5.** Cypher label injection from plugin manifests — `src/imbi_api/endpoints/plugin_entities.py:179, 220, 249, 315, 340` and `src/imbi_api/endpoints/plugin_edges.py:209-330`. Validate label/edge names against `^[A-Za-z][A-Za-z0-9_]*$` at both manifest registration and call site. Call-site half landed in PR #340; manifest-time validation in `imbi_common` follow-up still pending.
- [ ] **C6.** JWT secret falls back to per-process random — `imbi-common/.../settings.py:48-79`. Refuse to boot in non-dev mode when `IMBI_AUTH_JWT_SECRET` (and encryption key) are unset.
- [ ] **C7.** Search endpoint enumerates entire org into memory and post-filters vector results — `src/imbi_api/endpoints/search.py:30-95, 135-169`. Push org scoping into the pgvector query; ensure all relevant node types are covered.

---

## High — Auth / Authz

- [x] **H1.** Refresh-token reuse doesn't invalidate the whole chain — `src/imbi_api/endpoints/auth.py:496-522`. Refresh pairs now carry a `family_id`; on detected reuse the handler cascades a single Cypher `MATCH … SET revoked = true` across every un-revoked sibling. Legacy rows without `family_id` log ERROR and skip the cascade. — PR #347.
- [~] **H2.** SSRF in OIDC discovery — `src/imbi_api/auth/oauth.py:21-63`. Enforce HTTPS, block RFC1918 / link-local addresses. — PR #345 (open).
- [x] **H3.** Session-limit feature is dead code — `src/imbi_api/auth/sessions.py:18, 86-99` has no callers. Removed `enforce_session_limit`, `update_session_activity`, `max_concurrent_sessions`, `session_timeout_seconds` along with their tests. — landed on `main` (f0f15eb).
- [x] **H4.** Login timing oracle — `src/imbi_api/endpoints/auth.py:272-313`. Login now always runs Argon2 (against the real hash or a module-level dummy hash) and collapses every 401-class failure to a single generic message. — PR #344.
- [x] **H5.** Argon2 blocks the event loop — `src/imbi_api/auth/password.py`. Every production call site (login, API-key auth, MFA setup/verify/disable, password change, user/key/credential create + rotate) now wraps Argon2 in `asyncio.to_thread`; the 10 MFA backup-code hashes run via `asyncio.gather`. — PR #344.
- [x] **H6.** MFA backup-code reuse race — `src/imbi_api/endpoints/auth.py:386-403`, `src/imbi_api/endpoints/mfa.py:281-289`. Both backup-code paths fold verify-and-consume into a single atomic Cypher statement (`WHERE {used_hash} IN t.backup_codes SET t.backup_codes = [c IN ... WHERE c <> {used_hash}]`); empty result = race-lost, treated as 401. Also drops the stale `json.dumps(backup_codes)` write that was coercing the AGE list to a JSON string. — PR #346.
- [x] **H7.** `roles.grant_permission` / `revoke_permission` don't check `is_system` — `src/imbi_api/endpoints/roles.py:448-567` allows privilege escalation by mutating system roles. — PR #343.
- [x] **H8.** Upload read paths are unauthenticated — `src/imbi_api/endpoints/uploads.py:192-262` (`get_upload`, `get_upload_meta`, `get_upload_thumbnail`). Add `require_permission('upload:read')`. — PR #343.
- [x] **H9.** `/events` cursor leaks across projects — `src/imbi_api/endpoints/events.py:201-264`. Now gated on new seeded `admin:events:read` permission; org-scoped variant stays on `project:read`. — PR #343.

## High — Cypher / DB Correctness

- [x] **H10.** AGE retry reuses `CREATE` for `OWNED_BY` / `TYPE` — `src/imbi_api/endpoints/projects.py:1699, 1710, 1913-1935`. Switch to `MERGE` so retries are idempotent (mirror the `DEPLOYED_IN` fix at 1718). — PR #338.
- [x] **H11.** Plugin assignment replace is non-transactional — `src/imbi_api/endpoints/project_plugins.py:160-203`, `src/imbi_api/endpoints/project_type_plugins.py:130-169`, `src/imbi_api/endpoints/service_plugins.py:815-867`. Wrap in a transaction or batch with `UNWIND ... CREATE`. — PR #379 collapsed the project + project-type flows into a single ``UNWIND`` detach-and-recreate; the `service_plugins` half now fuses delete + UNWIND-create + default-demotion into one statement too. Also fixed a latent duplicate-edge bug in `assignment_writer.replace_assignments`: the post-DELETE `OPTIONAL MATCH` rows must be collapsed with `count(old)` before the `UNWIND`, otherwise a parent with K≥2 prior edges produced K×N edges. Both queries were verified against the live Apache AGE dev database (`just docker`): the dedup collapse yields exactly N edges, and the service fused query correctly deletes, recreates, round-trips JSON options, and demotes competing sibling defaults.
- [x] **H12.** `service_plugins.replace_plugin_assignments` skips `validate_one_default_per_tab` (compare `project_plugins.py:117-124`). — Not applicable: this endpoint is the inverted shape (one plugin → many project types). `validate_one_default_per_tab` groups solely by `tab`, so applying it verbatim would wrongly reject the same plugin being default on one tab across multiple project types. The body already rejects duplicate `(project_type, tab)` pairs, and cross-plugin default conflicts are resolved by the default-demotion step in the fused replace. No code change beyond H11.

## High — Performance / Hot Path

- [x] **H13.** Audit / event writes run inline on PATCH / deploy — `src/imbi_api/endpoints/projects.py:2089`, `src/imbi_api/endpoints/project_deployments.py:444`. Move to `BackgroundTasks`. ``patch_project`` schedules ``_emit_change_events`` via ``fastapi.BackgroundTasks`` and ``trigger_deployment`` threads ``background`` through ``_handle_deploy`` / ``_handle_promote`` so both audit sites schedule ``_record_deployment_audit`` instead of awaiting it. — PR #372.
- [x] **H14.** `list_current_releases` fires 2N upstream HTTP calls per project page with no cap — `src/imbi_api/endpoints/releases.py:346-367`. Add a shared semaphore and per-request `(project_id, committish)` cache. — PR #377 added a module-level `asyncio.Semaphore` cap and de-duplicated `(project_id, committish)` lookups so a paginated release-train fetch makes at most N capped upstream calls instead of 2N unbounded ones.
- [x] **H15.** `backfill_embeddings.py:54-57` unconditionally re-embeds every node serially, calls private `_auto_embed`, no rate limiting. Add idempotency check, batching, and `asyncio.Semaphore`. — PR #378 added a `--force` flag, a `SELECT DISTINCT node_id FROM public.embeddings` skip-set for resumability, an `asyncio.Semaphore(--concurrency)` cap shared across all node types, and `psycopg.Error` swallowing so one bad node no longer aborts the run.
- [x] **H16.** OpenAPI `_schema_cache` regenerates concurrently under cold load — `src/imbi_api/openapi.py:202-280`. Wrap with `asyncio.Lock` or precompute at startup. Wrapped the check + build in a ``threading.Lock`` with double-check; pulled the build body into ``_build_schema`` so the locked section is straight-line. ``clear_schema_cache`` also takes the lock so an in-flight build can't re-populate after a clear. — PR #366.
- [x] **H17.** Per-call ClickHouse insert in lifecycle dispatch — `src/imbi_api/plugins/lifecycle_dispatch.py:240-268`. Batch or use the existing event writer queue. ``dispatch_lifecycle`` now collects every invocation into a single ``_emit_events_batch`` insert at the end of the loop instead of one ``_emit_event`` per plugin — N round trips → 1. — PR #373.

## High — Boot / Lifespans

- [ ] **H18.** Module-global `_graph` in `src/imbi_api/lifespans.py:43` couples worker startup to import order. Pass via `context.get_state(graph.graph_lifespan)`.
- [~] **H19.** Boot exceptions silently warning-logged — `src/imbi_api/lifespans.py:35, 39`. Elevated both to `LOGGER.exception` so the traceback is captured (landed on `main`); the healthcheck-flag half remains — needs a `/status` redesign.
- [x] **H20.** `StorageClient.__init__` bypasses TOML config — `src/imbi_api/storage/client.py:29`; same pattern in `src/imbi_api/storage/thumbnails.py:58` and `src/imbi_api/endpoints/uploads.py:80`. Added `settings.get_storage_settings()` (TOML-aware singleton mirroring `get_server_config`) and routed all three sites + `storage/validation.py` through it. — landed on `main`.
- [x] **H21.** Admin user setup ignores membership-write outcome — `src/imbi_api/entrypoint.py:451-465`. `_create_admin_user` now captures the MERGE-edge row count and raises `RuntimeError` with the email + org slug in the message when the membership write returns zero rows. — PR #349.
- [~] **H22.** OpenAPI `/docs` URL ignores `api_prefix` — `src/imbi_api/app.py:81-85`, `src/imbi_api/openapi.py:424`. _(Re-examined: documented as deliberate in `settings.py:60-63` — "The /docs and /openapi.json endpoints are always served at the root regardless of the prefix" — and matches the orchestrator's `/docs` → imbi-api root routing in the parent `imbi/CLAUDE.md`. No action needed.)_

---

## Medium — Duplication / Refactor Opportunities

(Highest LOC-reduction ROI.)

- [ ] **M1.** Extract pagination helpers (`_encode_cursor`, `_decode_cursor`, `_build_link_header`, `_parse_iso`) into `_helpers.py` / new `_pagination.py`. Duplicated verbatim across `src/imbi_api/endpoints/user_activity.py:661-710`, `operations_log.py:107-135, 337-357`, `documents.py:77+`, `events.py:48+`.
- [ ] **M2.** Extract `fetch_or_404` helper. Cloned in `releases.py:238`, `third_party_services.py:1015`, `documents.py:444`, `document_templates.py:204`, `plugin_entities.py:173`.
- [ ] **M3.** Wrap `psycopg.errors.UniqueViolation → 409` in a decorator (26+ duplicates).
- [ ] **M4.** Extract `_serialize_json_fields` / `_deserialize_json_fields` (defined in `third_party_services.py:56-83`); re-implemented ad hoc in `projects.py:873-878, 1873-1875` and `documents.py`.
- [ ] **M5.** Build a `BlueprintScopedRouter(label, alias, related_counts)` factory. `_persist_team`, `_persist_project_type`, `_persist_environment`, `_persist_link_definition` are line-for-line clones (`teams.py:44-138`, `project_types.py:37-134`, `environments.py:38-133`, `link_definitions.py:70-161`). Est. -1,400 LOC.
- [~] **M6.** `link_definitions.py:99` missing the `payload.pop('organization*', None)` strip the other three have — drift bug. _(Re-examined: `LinkDefinitionCreate` is a typed Pydantic model with no `organization`/`organization_slug` fields, so the pop is unnecessary there. The other three accept `dict[str, typing.Any]` to support blueprint extension.)_
- [ ] **M7.** Consolidate TOTP verification, duplicated in `endpoints/auth.py:344-417`, `endpoints/mfa.py:230-291`, `endpoints/mfa.py:389-443`.
- [ ] **M8.** Consolidate API-key creation between `endpoints/api_keys.py:99-195` and `endpoints/sa_api_keys.py:64-169`; `client_credentials.py:97-172` repeats it again.
- [x] **M9.** Consolidate three definitions of `parse_options` / `_parse_options` (`plugins/__init__`, `plugins/assignments.py`, `identity/flows.py`). — `plugins.parse_options` is now the single robust implementation: it calls `graph.parse_agtype` so it subsumes raw agtype column values, the single JSON-encoded strings AGE returns for nested maps, and already-parsed dicts, and yields `{}` for `None`/malformed/non-object input. `identity/flows._parse_options` was removed and routed through it; `identity/resolution.py:140` dropped its now-redundant manual `parse_agtype`. (`plugins/assignments.py` already imported the shared one.)
- [x] **M10.** Extract plugin-assignment writer (`plugins/assignment_writer.py`) — see H11/H12 for bugs this would prevent. — PR #379 added `src/imbi_api/plugins/assignment_writer.py` with a shared transactional `replace_assignments` helper and routed the project and project-type endpoints through it, eliminating the duplicated multi-Cypher dance.

## Medium — Correctness

- [ ] **M11.** JSON-Patch round-trip is lossy for `HttpUrl | str` unions — `endpoints/blueprints.py:254`, `organizations.py:442`, `roles.py:351`, `teams.py:392`, `link_definitions.py:427`, `environments.py:403`, `project_types.py:395`. Avoid `model_dump(mode='json')` round-trip on patchable fields, or re-validate against a base model.
- [x] **M12.** `extra='allow'` on response models leaks internals — `src/imbi_api/domain/models.py:679, 922, 1126`. Switched all three (`ThirdPartyServiceResponse`, `LogEntryResponse`, `WebhookResponse`) to `extra='ignore'` so undeclared fields are dropped from the wire shape. — PR #351.
- [ ] **M13.** Audit `ServiceApplication` for plaintext `client_secret` exposure once C1 is resolved — `endpoints/auth_providers.py:354, 397, 535`.
- [x] **M14.** PII in login-failure logs — `endpoints/auth.py:277, 288, 299, 309` log full emails. Added `_redact_email()` keeping domain + first char of local; applied to all three remaining log sites (login-failure, rehash, successful login). — PR #350.
- [x] **M15.** `authenticate_api_key` round-trips per request even when throttled — `auth/permissions.py:455, 477`. Added a per-process bounded ``OrderedDict`` cache keyed on SHA-256(key) with 60 s TTL and 1024-entry cap. Hits return the cached AuthContext and skip the DB + Argon2 work; ``clear_api_key_cache()`` exposed for tests and in-process invalidation. — PR #368.
- [ ] **M16.** `find_or_create_oauth_identity` does 5 graph round-trips — `endpoints/auth.py:1156-1207`.
- [x] **M17.** `dispatch_lifecycle` ignores plugin `enabled` flag — `plugins/lifecycle_dispatch.py:79-101`, `plugins/resolution.py:228`. Moved the enabled check into the resolver: `resolve_plugin` raises `PluginUnavailableError` when the chosen plugin's PluginRegistration is disabled; `resolve_all_plugins` issues a single `get_enabled_map` round-trip and silently skips disabled plugins with an INFO log. — PR #355.
- [x] **M18.** `revoke_connection` swallows IdP-side failures — `identity/flows.py:417-434`. Now returns a structured `RevokeOutcome(idp_revoked, idp_error)`; the disconnect endpoint switches from 204 to 200 OK with a JSON body containing the IdP error message when local revoke succeeds but the IdP rejects the call. — PR #359.
- [ ] **M19.** `patch_plugin_configuration` is last-writer-wins — `plugins/credentials.py:196-225`. Take a Valkey lock or single-query merge.
- [x] **M20.** `rescore_all` fires N parallel Valkey calls — `endpoints/scoring.py:578-586`. Pipeline / Lua. Added ``score_queue.enqueue_recompute_bulk`` that pipelines N ``SET NX EX`` debounce checks and N ``XADD`` calls into two round trips; the rescore endpoint replaced its ``asyncio.gather`` loop with the bulk helper. — PR #371.
- [ ] **M21.** `score_history_by_team` builds a `project_id IN [...10k...]` clause — `endpoints/scoring.py:358-427`. Denormalize team_slug or use a CH dictionary.
- [~] **M22.** `link_definitions` count uses substring match — `endpoints/link_definitions.py:188-196, 244-247, 336-339`. _(Re-examined: the current pattern is `p.links CONTAINS ('"' + ld.slug + '":')`, which anchors on the closing quote + colon and so does not let `foo` match `foobar`. No action needed.)_
- [x] **M23.** `compute_score` exception silently swallowed — `endpoints/projects.py:1374-1375`. Replaced `pass` with `LOGGER.warning(..., exc_info=True)`. — landed on `main`.
- [ ] **M24.** Search `attribute` filter is post-applied — `endpoints/search.py:150-151`. Push into `db.search()`.
- [x] **M25.** Drop `del auth` lines — `releases.py:549, 702, 729, 1132, 1233, 1291`; `user_activity.py:355, 516, 598`. _(Also covered `user_activity.py:1006` and `users.py:382` for consistency.)_ — landed on `main` (6c9a365).
- [x] **M26.** Dead `presigned_url` with 1h TTL — `storage/client.py:143-168`. Removed the method (no production caller; only tests referenced it) and dropped the corresponding tests. — landed on `main`.
- [x] **M27.** Pillow decompression-bomb guard missing — `storage/thumbnails.py:86-90`. Set `PIL.Image.MAX_IMAGE_PIXELS` and convert warnings to errors. Wrap `UnidentifiedImageError`/`OSError`. Lowered Pillow's pixel cap to 64MP, promoted `DecompressionBombWarning` to an error, and wrapped `UnidentifiedImageError`/`DecompressionBomb*`/`OSError` into a `ValueError` so the upload pipeline rejects rather than silently allocating gigs of RAM. — landed on `main`.
- [x] **M28.** Upload `filename` passed unsanitized into S3 key — `endpoints/uploads.py:95`. S3 key now uses `_safe_s3_basename(filename)` (collapse anything outside `[A-Za-z0-9._-]` to `-`, strip leading/trailing punctuation, cap at 128, fall back to `'file'`); the unmodified ``filename`` still lives on the `Upload` model for display. — landed on `main` (no separate `display_filename` field — the existing `filename` is already preserved unchanged).
- [x] **M29.** `_subscribe_reload` imports private `_audit_unavailable` — `plugins/reload.py:14-16`. Renamed to public `audit_unavailable` and updated both call sites + tests. — landed on `main`.
- [x] **M30.** OIDC discovery cache process-local and unbounded — `auth/oauth.py:17`. Capped at 64 entries; oldest entry by insertion timestamp is evicted on next successful insertion. TTL behavior preserved. — PR #354.
- [x] **M31.** OAuth state JWT is 10-min TTL and not single-use — `auth/oauth.py:97`. `verify_oauth_state` now atomically marks the embedded nonce as consumed via Valkey `SET NX EX`; replays raise `ValueError`. Missing-Valkey path raises `RuntimeError` (caller maps it to the auth-failed redirect). — PR #356.
- [x] **M32.** Rate-limit gaps: `/mfa/verify` (TOTP brute), `/auth/logout`, `/auth/oauth/{p}/callback` (outbound amplification), `/auth/token` client-id scanning. Added slowapi decorators: `/mfa/verify` → 5/minute, `/auth/logout` → 30/minute, `/auth/oauth/{p}/callback` → 10/minute. `/auth/token` already carried 10/minute. — PR #357.
- [x] **M33.** Settings singletons aren't resettable — `settings.py:212-243`. Added `settings.clear_caches()` that resets the auth/server/storage singletons for tests. — landed on `main`.
- [~] **M34.** Sweeper double-marks expired — `identity/sweeper.py:59-97` overlaps with `flows.refresh_connection`. _(Re-examined: the sweeper already guards with `if connection.status != 'expired'` before re-marking — `flows.refresh_connection` flips to `expired` for plugin-level failures, the sweeper only owns the missing-refresh-token branch. No double-mark in practice.)_
- [x] **M35.** `_create_membership_query` doesn't validate role existence — `auth/membership.py:44-49`. Added a `MATCH (r:Role {slug: {role_slug}})` clause so MERGE only fires when the role node exists (and uses `r.slug` on the edge to keep the property in sync). — landed on `main`.
- [x] **M36.** `check_resource_permission` resource-type → label mapping is brittle — `auth/permissions.py:606-624`, mapping at 678 (`project_logs` → `ProjectLogs` vs actual `ProjectLog`). Replaced the ``''.join(w.capitalize() ...)`` derivation with an explicit ``_RESOURCE_LABEL_MAP`` and a ``_resolve_resource_label`` helper that raises ``KeyError`` for unmapped types — a missing entry now surfaces as a 500 instead of a silent 403. — PR #363.
- [ ] **M37.** Inconsistent trailing-slash policy and `name=` decorations across routers. Decide on `response_model=` vs return annotation and pick one.
- [x] **M38.** Cap per-request `_TPS_RESYNC_CONCURRENCY` globally — `third_party_services.py:33, 574`. Currently 5 per request, so 2 admins = 10 simultaneous. Replaced the per-request `asyncio.Semaphore` with a module-level `_TPS_RESYNC_SEMAPHORE` so concurrent admin clicks share the 5-slot budget. — landed on `main`.
- [x] **M39.** `_fetch_current_releases` fully parses every event to find latest timestamp — `endpoints/projects.py:550-555`. Replaced `_parse_deployment_events` with `_latest_deployment_event`, which scans the JSON dict list once and returns `(timestamp, performed_by)` for the most recent entry without paying for per-entry Pydantic validation. — PR #375.
- [ ] **M40.** `_attach_project_relationships` and `_flatten_edge_props` mutate dicts before pydantic validation — `endpoints/projects.py:700, 985`. Use `model_validator(mode='before')`.
- [x] **M41.** `list_promotion_options` does adjacent env pairs serially — `endpoints/project_deployments.py:1770-1818`. Use `asyncio.gather`. Collected adjacent-env pairs first, then fan the per-pair `handler.compare()` calls out through `asyncio.gather`; the popover RTT is now driven by the slowest plugin call, not the sum. — landed on `main`.
- [x] **M42.** Plugin entity `props_template` consumers pass `str` instead of `LiteralString` — `endpoints/service_plugins.py:168, 183, 193, 858`. `props_template` / `set_clause` now return `typing.LiteralString` (safe since L29's identifier validator constrains the dynamic part) and the three `create_query` / `update_query` annotations in `service_plugins.py` are tightened to `typing.LiteralString`. — landed on `main`.
- [~] **M43.** `_emit_change_events` errors silently swallowed — `endpoints/projects.py:664-667`. _(Re-examined: already uses `LOGGER.exception(...)` at the `except` site; no action needed.)_
- [x] **M44.** `_load_plugin_handler` falls back from id to slug match — `identity/flows.py:46-83`. Make disambiguation explicit. Added keyword-only ``lookup: Literal['auto', 'id', 'slug']``; ``'auto'`` (default) preserves the fallback but logs at INFO when it fires, so any silent reliance on it surfaces in production logs. Explicit ``'id'`` / ``'slug'`` short-circuit to one query. — PR #365.
- [x] **M45.** Identity sweeper lock TTL (10s) shorter than slow IdP refresh — `identity/sweeper.py:27`. Bump to 60s (matches `POLL_INTERVAL_SECONDS`) so the lock covers a slow refresh but cannot outlast the next sweep tick if a worker dies. — landed on `main`.

---

## Low

- [~] **L1.** `app.py:30` passes the `version` module to FastAPI instead of `version.__version__`. _(Re-examined: `from imbi_api import version` imports the string assigned in `__init__.py` via `metadata.version('imbi-api')`, not a module. No bug.)_
- [~] **L2.** `app.py:43-46` hardcodes `/status`, `/api/status` ignoring `api_prefix`. _(Re-examined: existing comment documents this as deliberate — middleware lists both paths so it's deployment-agnostic regardless of the runtime `IMBI_API_URL` prefix.)_
- [~] **L3.** `middleware/rate_limit.py:51` uses private `slowapi._rate_limit_exceeded_handler`. _(Re-examined: slowapi exposes no public alias for this handler, and rolling our own would also need the private `Limiter._inject_headers` to keep the countdown headers. Leaving the private import — no public API exists to migrate to.)_
- [x] **L4.** Mark `parse_scopes` deprecated and document migration deadline — `models.py:82-104`. Decorated with `warnings.deprecated` (PEP 702) so type-checkers and IDEs flag callers; `reportDeprecated` demoted to warning globally in `pyproject.toml` so existing call sites don't block CI before the migration completes. — PR #358.
- [~] **L5.** `LocalAuthConfig.updated_at: datetime | None` has a factory that always returns `datetime` — `domain/models.py:189-192`. _(Re-examined: narrowing to `datetime` triggered `reportIncompatibleVariableOverride` against the `GraphModel` parent — pydantic mutable fields can't be narrowed past the parent. Reverted to `datetime | None` with a comment explaining the invariance constraint.)_
- [x] **L6.** `endpoints/status.py:19-21` is unauthenticated and exposes the `version` string. Dropped the `version` field from `StatusResponse` so liveness/readiness probes still work but the build version isn't leaked pre-auth. — PR #352.
- [x] **L7.** Tag slug derivation accepts blank name (empty slug) — `endpoints/tags.py:77`. Add `Field(min_length=1)`. — PR #339.
- [x] **L8.** `db.merge(blueprint)` without explicit `match_on` in create path — `endpoints/blueprints.py:99` (cf. line 288). — PR #339.
- [x] **L9.** Org slug rename doesn't store `previous_slugs` for redirect resolution — `endpoints/organizations.py:316-403`. ``_persist_organization`` now, on the rename path only, fetches the existing ``previous_slugs`` and appends the about-to-be-replaced slug. Future redirect resolution can be layered on by MATCHing ``WHERE {old_slug} IN n.previous_slugs``. — PR #367.
- [x] **L10.** `patch.py:9` indirect `__import__('logging')`. Replace with normal import. — landed on `main` (6c9a365).
- [x] **L11.** `relationships.py:11-23` accepts `dict[str, tuple[str, int]]` — switch to a `NamedTuple` to prevent positional swaps. Switched to a frozen ``RelationshipSpec(suffix, count)`` dataclass (``NamedTuple`` collided with ``tuple.count``) and updated the five call sites. — PR #360.
- [~] **L12.** `entrypoint.py:53-80, 86-118, 289-326` reimplements Cypher templating that `graph_sql.py` provides. Routed ``_create_admin_user``'s 6-field MERGE+SET through ``set_clause``; the other sites the punchlist mentioned only set a single literal field each, so the helper doesn't save anything there. — PR #370.
- [x] **L13.** `entrypoint.py:218, 222` `raise typer.Exit(code=1) from None` is cargo-culted; remove. — landed on `main` (6c9a365).
- [x] **L14.** OpenAPI generator has 5 `except Exception:` swallows — `openapi.py:90, 146, 244, 256, 271`. Bust cache on partial failure. ``_build_schema`` now returns ``(schema, had_failure)`` and the locked ``custom_openapi`` skips the cache assignment when any per-model schema generation raised — broken results stay out of the cache so the next request retries from scratch instead of pinning the partial schema for the worker's lifetime. — PR #369.
- [~] **L15.** `graph_sql.py:11-26` helpers barely used; either adopt or delete. _(Re-examined: 45 call sites across 13 endpoint modules now — well-adopted; no action needed.)_
- [x] **L16.** `_extract_http_detail` doesn't preserve `start_url` from `identity_required` — `plugins/lifecycle_dispatch.py:216-225`. Formatter now appends `start_url=...` alongside `plugin_id=...` so the lifecycle event log reproduces the re-auth handoff the UI shows. — landed on `main`.
- [x] **L17.** `_replace_state` doesn't validate HTTPS — `identity/flows.py:182-191`. Raises `ValueError` on any non-HTTPS scheme unless the host is a local loopback (`localhost`, `127.0.0.1`, `::1`) so dev fixtures still work but a misconfigured manifest can't smuggle the state JWT over cleartext. — PR #353.
- [x] **L18.** `score_history_feed` filters out non-existent empty-string `change_reason` — `endpoints/scoring.py:462, 499`. Removed the dead ``change_reason != ''`` predicate — ``record_score_change`` callers always pass a non-empty reason (``'attribute_change'`` fallback), so the filter only added cost; the defensive read-side empty→``None`` conversion stayed in place. — PR #361.
- [x] **L19.** `_set_widget_text_override` creates registration with no `enabled` flag — `endpoints/admin_plugins.py:330-344`. Both MERGE branches now `SET r.enabled = coalesce(r.enabled, false)`, mirroring `_seed_registrations`. — landed on `main`.
- [x] **L20.** Manual `urllib.parse.unquote(email)` double-decodes path params — `endpoints/user_activity.py:356, 519, 599, 1012`. FastAPI already URL-decodes path params; removed the four redundant calls. — landed on `main`.
- [x] **L21.** `_release_id_for` `LIMIT 1` hides duplicate (committish, tag) — `endpoints/project_deployments.py:529-548`. Drop the `LIMIT 1`, log a warning when more than one row comes back, and continue returning the first. — landed on `main`.
- [x] **L22.** Plugin-controlled URLs (`run_url`, `release_url`) stored in audit JSON; confirm UI escapes — `endpoints/project_deployments.py:417-426`. — PR #380 added a `_safe_audit_url` helper that drops any non-`http(s)` plugin-supplied URL before it reaches the audit JSON, neutralizing `javascript:` / `data:` / other dangerous schemes at the source.
- [x] **L23.** `list_service_applications` `usage='login'` drops `org_slug` scoping — `endpoints/third_party_services.py:705-734`. Documented the intentional cross-org behavior in the handler docstring: login providers are inherently global, only names/slugs are exposed (no `client_secret`), `org_slug` still gates the route via `third_party_service:read`, and any future restriction should land via a new `auth_provider:list_global` permission. — PR #376.
- [x] **L24.** `_handle_deploy` writes audit row even when no release matched — `endpoints/project_deployments.py:1086-1097`. Suppresses the ``_record_deployment_audit`` call when ``append_deployment_event`` never matched a Release; the response still returns ``recorded=False`` so the UI knows the workflow was dispatched but no internal release history was touched. — PR #362.
- [x] **L25.** `_RELEASE_NOTES_SYSTEM` reads from `importlib.resources` at import — `project_deployments.py:1504-1508`. Replaced with `@functools.cache`'d `_release_notes_system()` accessor so the read happens on first use, not module import. — landed on `main`.
- [~] **L26.** `_load_user_identities` swallows all exceptions — `auth/permissions.py:184-190`. _(Re-examined: the swallow already logs `exc_info=True` so failures are visible; only the "add metric" half remains, which is deferred until we adopt a metrics pipeline.)_
- [x] **L27.** `parse_scopes` accepts any string — `auth/permissions.py:438`. Validate against seeded `Permission` set. Added ``load_all_permission_names`` + ``validate_scopes`` and called the latter at the top of the three credential-create endpoints (api_keys, sa_api_keys, client_credentials). Bogus scopes now 400 at write time instead of silently surviving the round-trip. — PR #364.
- [x] **L28.** `ensure_user_membership` falls back to 'default' org silently — `auth/membership.py:139-141`. Log at INFO when the multi-org tenant falls back so the "why did the new user land in `default`?" answer is visible in the logs. — landed on `main`.
- [x] **L29.** `delete_application_secret` passes a path param into `set_clause` — verify `graph_sql.set_clause` rejects non-identifier keys (`endpoints/third_party_services.py:1510, 1532, 1548`). `set_clause` / `props_template` now defensively reject any key that isn't `^[A-Za-z_][A-Za-z0-9_]*$` (call site already pre-filters against `models.SECRET_FIELDS`, but the helper is now safe on its own). — landed on `main`.
- [ ] **L30.** `list_service_webhooks` uses unpaginated `collect()` — `endpoints/third_party_services.py:638-674`.

---

## Test Suite

- [ ] **T1.** Add `tearDown` to test files that mutate module-level state (most do not). `test_auth.py` is the model.
- [ ] **T2.** Stop defaulting to `AuthContext(permissions=set(), is_admin=True)` — short-circuits permission enforcement. Add non-admin coverage in `test_admin.py`, `test_blueprints.py`, `test_uploads.py`, `test_events.py`, `test_roles.py`.
- [ ] **T3.** Stop mocking `parse_agtype` as identity — e.g. `test_organizations.py:148-152`. Use real agtype strings (as `test_search.py:81-83` does).
- [ ] **T4.** Add integration test fixture against a real PostgreSQL+AGE container. Current ~30% coverage gap is almost entirely Cypher-template validation.
- [ ] **T5.** Stop mocking `validate_upload` — `test_uploads.py:81-82, 111-112, 148`. Cover bad-magic-byte uploads end-to-end.
- [ ] **T6.** Add cross-org IDOR tests, especially `pull_requests.py:186-194` org-scope boundary.
- [ ] **T7.** Cover `search.py:135-169` batch-growth retry loop (currently 100% mocked).
- [ ] **T8.** Cover `project_configuration` plugin-credentials-missing path, audit-on-failure, and cache invalidation behavior.

---

## Recommended fix order

1. C1 (syntax errors blocking imports).
2. C2 + C3 + C4 + C5 + C6 (security criticals).
3. C7 (DoS in search).
4. H8 (unauthenticated upload reads) + H7 (system-role privilege escalation) + H9 (cross-project event leak).
5. H10 (AGE retry idempotency) + H13 (move audit writes off hot path).
6. H4, H5, H6 (auth hardening).
7. M1-M10 (refactor wave) — removes class of drift bugs (M6 already bit).
8. T4 (real DB integration tests) — unlocks confident Cypher refactoring.
9. Everything else.
