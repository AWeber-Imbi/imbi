# Imbi relational schema

This directory is the schema of record for the relational PostgreSQL
database that replaces the Apache AGE graph. The design follows
`docs/age-to-relational-evaluation.md` and
`docs/age-to-relational-implementation-plan.md` in the Imbi meta
repository. The reviews of 2026-09-29 are in
`docs/age-to-relational-schema-review/` (the second one in its
`second-review/` folder) in the same repository.

## Tool

The schema is a [pglifecycle](https://gmr.github.io/pglifecycle/) project.
Each database object is one YAML file, validated against the pglifecycle
JSON schemata. There are no hand-written migration files. pglifecycle
compares the project with a live database and writes the DDL that makes
the database match.

The project needs a pglifecycle build that supports row-level security
(`row_level_security` and `policies` in table files) and
`on_delete_columns` on foreign keys. No release has these yet, so the
project is pinned to one commit of pglifecycle `main`:

**Pinned pglifecycle commit:** `4f6729cda43b1d8facdeed304e6adfeb4991d18a`
(2026-09-30, "Merge pull request #113"; the binary reports
2.0.0-alpha.2).

`scripts/install-pglifecycle.sh` holds the pin. It builds that commit
with `cargo install` and prints the path of the binary. The moon tasks
and CI use it, so they use the same build. When you change the pin,
change it in the script and here in the same commit, and run
`moon run root:schema-check`. The cutover runbook records the SHA-256 of
the binary that the rehearsal and the cutover use.

| moon task | What it does |
|---|---|
| `moon run root:schema-plan -- <database>` | Prints the DDL that makes the database match the project |
| `moon run root:schema-apply -- <database>` | `deploy --apply`, then `scripts/set-owners.sql` |
| `moon run root:schema-check` | `build`; a new database; `schema-apply`; a second deploy that must be equal to `tests/second-deploy-allowlist.sql`; the pgTAP files `tests/test_*.sql`; drops the database |

The tasks connect with the libpq variables (`PGHOST`, `PGPORT`,
`PGUSER`, `PGPASSWORD`). When `PGHOST` is not set, they use
`POSTGRES_URL` from `.env.test` (`moon run root:services` writes it).
`schema-apply` refuses a database that has the legacy `public.embeddings`
table of the AGE-era app. `schema-check` puts a marker comment on each
database that it makes (the check database and `<name>_test`), and drops
only a database with that marker: it refuses a name that another
database already has. It fails when `tests/` has no `test_*.sql` file.

| Command | What it does |
|---|---|
| `pglifecycle build schemata/ schema.dump` | Validates every file and writes a `pg_restore` archive |
| `pglifecycle deploy -d imbi schemata/` | Prints the DDL that makes the database match the project |
| `pglifecycle deploy -d imbi --apply schemata/` | Runs that DDL in one transaction |

Automation never uses `--allow-drop`. A person applies a destructive
change from the printed plan.

While the AGE graph and the scheduler tables are still in the same
database, run `deploy` with these flags so that it does not propose to
drop them:

```
-N imbi -N ag_catalog -N scheduler --exclude-extension age --exclude-extension pg_cron
```

The project does not install pg_cron: no code uses it, and the extension
can only be created in the database that `cron.database_name` names. The
last flag keeps an existing pg_cron installation.

## Layout

| Path | Contents |
|---|---|
| `project.yaml` | Database settings and the `vector` extension |
| `tables/public/*.yaml` | One file per table (74) |
| `domains/public/*.yaml` | `jsonb_object`, `jsonb_array`, `slug` |
| `functions/public/*.yaml` | 13 functions: the two setting readers, 5 trigger functions, 6 lookup functions (see below) |
| `roles/*.yaml` | `imbi_owner`, `imbi_definer`, `imbi_trigger`, and the `PUBLIC` revocations |
| `users/*.yaml` | `imbi_app`, `imbi_admin`, `imbi_maintenance` and their grants |
| `registry.toml` | The tenancy scope of every table |
| `scripts/` | `create-roles.sql`, `set-owners.sql` (an owner check), the pglifecycle install script, and `schema.sh` for the moon tasks |
| `tests/` | The pgTAP files of `root:schema-check`, and the second-deploy allowlist |

All tables are in the `public` schema. The AGE graph uses the schema
`imbi`, so the relational tables cannot use that name while both exist.

## Roles

`deploy` applies grants and, in the pinned build, sets the owner that
each YAML file names (pglifecycle commit `47c58cc`). It does not create
roles. Create the roles before the first deploy with
`scripts/create-roles.sql`, which takes the three login passwords from
the psql variables `app_password`, `admin_password`, and
`maintenance_password`, and creates only the roles that do not exist.
It stops with an error, before it creates a role, when a variable is not
set, and it stops when an existing role has `LOGIN`, `BYPASSRLS`, or
`SUPERUSER` set differently from this list. The postgres service of `compose.ci.yaml` runs it at init, and
`moon run root:services` runs it again. It has these statements:

```sql
CREATE ROLE imbi_owner NOLOGIN;
CREATE ROLE imbi_definer NOLOGIN BYPASSRLS;
CREATE ROLE imbi_trigger NOLOGIN BYPASSRLS;
CREATE ROLE imbi_app LOGIN PASSWORD '...';
CREATE ROLE imbi_admin LOGIN PASSWORD '...';
CREATE ROLE imbi_maintenance LOGIN BYPASSRLS PASSWORD '...';
```

| Role | Use |
|---|---|
| `imbi_owner` | Owns the tables and the other functions. Cannot log in. |
| `imbi_definer` | Owns the SECURITY DEFINER lookup functions and nothing else. BYPASSRLS, and only SELECT on the tables that they read. |
| `imbi_trigger` | Owns `delete_embeddings()` and `delete_plugin_edges()` and nothing else. BYPASSRLS, and only SELECT and DELETE on `embeddings` and `plugin_edges`. No login role is a member of it. See Delete behavior. |
| `imbi_app` | The application login. No BYPASSRLS. Only SELECT and INSERT on the shared catalog, and only SELECT on `tenants`. |
| `imbi_admin` | The instance admin endpoints, in their own pool, after the application checks `users.is_admin`. Can read and write only the instance sign-in providers: `organization_isolation` on `integrations` applies to `imbi_app` only. The admin pool rejects an `imbi.organization_id` setting. No BYPASSRLS. |
| `imbi_maintenance` | The data migration, the reconciliation report, and catalog cleanup. BYPASSRLS. The application never uses it. |

The owners that the YAML files name, and that `deploy` sets, are these.
`scripts/set-owners.sql` does not change owners: it stops with an error
when an object in `public` has an owner that is not in this list. Run it
after each deploy (`schema-apply` does). It makes no changes, so it can
run in the cutover transaction.

```sql
-- every table, and the functions that are not SECURITY DEFINER
ALTER TABLE public.<table> OWNER TO imbi_owner;
ALTER FUNCTION public.<function>(...) OWNER TO imbi_owner;
-- the SECURITY DEFINER functions
ALTER FUNCTION public.principal_permissions() OWNER TO imbi_definer;
ALTER FUNCTION public.principal_memberships() OWNER TO imbi_definer;
ALTER FUNCTION public.principal_teams() OWNER TO imbi_definer;
ALTER FUNCTION public.webhook_organization_id(text) OWNER TO imbi_definer;
ALTER FUNCTION public.upload_organization_id(text) OWNER TO imbi_definer;
ALTER FUNCTION public.integration_organization_id(text) OWNER TO imbi_definer;
-- the trigger functions that delete rows of another table
ALTER FUNCTION public.delete_embeddings() OWNER TO imbi_trigger;
ALTER FUNCTION public.delete_plugin_edges() OWNER TO imbi_trigger;
```

A SECURITY DEFINER function that the deploying superuser still owns runs
as superuser. Do not deploy with `-O` (`--no-owner`).

`imbi_app` must not own the tables and must not have `BYPASSRLS`. If it
owns a table, `FORCE ROW LEVEL SECURITY` still applies, but the owner can
disable it.

## Conventions

- **Keys.** Every entity keeps its nanoid `id` as a `TEXT` primary key, so
  URLs, MCP tool output, and embeddings rows do not change. Join tables
  and tables without an id in the graph use natural composite keys.
  `issued_tokens` is the exception: its key is `jti`, because nothing
  reads a token id (Differences 17).
- **Collation.** Machine identifiers use `COLLATE "C"`: `id`, every
  `*_id` and `*_slug`, `slug`, `jti`, `storage_key`, and the
  `committish` columns, and any column that refers to one of these. They
  carry no language, `"C"` compares bytes, and a libc upgrade cannot
  change their index order. Names, titles, descriptions, `purl_name`, and
  all other text use the database default, which the operator picks at
  `initdb`, so a deployment in any locale sorts human text its own way.
  The generator checks that both sides of each foreign key have the same
  collation.
- **Tenancy.** Every organization-scoped table has `organization_id`,
  with a foreign key to `organizations`. It is NOT NULL, except in
  `integrations` (NULL for the instance sign-in provider). A table that
  other tables
  refer to has `UNIQUE (organization_id, id)`. A reference is a
  composite foreign key, `(organization_id, x_id)` to
  `x(organization_id, id)`. A row in one organization cannot refer to a
  row in a different organization.
- **Enumerations** are `TEXT` columns with a named `CHECK`. PostgreSQL
  enum types are not used, because `ALTER TYPE ... ADD VALUE` cannot run
  in the single transaction that `deploy --apply` uses.
- **Status columns** have the table's subject as a prefix
  (`deployment_status`, `blocker_status`). Timestamps end in `_at`.
- **JSONB** holds data whose shape the application defines: blueprint
  `attributes`, plugin options and credentials, maps such as
  `projects.links`. A JSONB column that must be an object uses the
  domain `jsonb_object`. A column that must be an array uses
  `jsonb_array`. The domain holds the `jsonb_typeof` check, so the
  tables do not repeat it.
- **No GIN indexes.** Under row-level security, PostgreSQL uses only a
  leakproof condition as an index condition. The jsonb operators
  (`@>`, `?`, `->>`), `LIKE`, regular expressions, and array operators
  are not leakproof, so for `imbi_app` they are always filters on the
  rows of one organization. A GIN index on `attributes` would never be
  used. For an attribute that lists filter on often, add a generated
  column with a btree index: text equality is leakproof.
- **Slugs** use the domain `slug`: lowercase letters and digits in
  groups that one hyphen separates. A table can add a stricter `CHECK`
  (`integrations`, `webhooks`, `service_accounts` require a leading
  letter and a maximum length). `analysis_results.slug` is plain text,
  because Doctor check names contain colons.
- **`updated_at`** is set by the trigger `<table>_set_updated_at`, which
  calls `set_updated_at()` before an `UPDATE` that changes the row
  (`WHEN (old.* IS DISTINCT FROM new.*)`). It uses
  `statement_timestamp()`, so `updated_at` cannot be earlier than a
  `created_at` that a later transaction wrote. The application does not
  set it. An `INSERT` does not fire the trigger, so the data migration
  keeps the timestamps from the graph.
- **`deployments.transitioned_at`** is the time of the last status
  change, from the provider clock. The application sets it, and changes
  it only when `deployment_status` changes: a note, run URL,
  `performed_by`, or `credential` change does not re-rank a deployment.
  The newest deployment is the one with the latest
  `(transitioned_at, id)`. The graph used `updated_at` for this, which
  the trigger cannot keep.
- **State timestamps.** A nullable `*_at` column records a state, with no
  boolean next to it: `revoked_at IS NOT NULL` means revoked
  (`api_keys`, `client_credentials`, `issued_tokens`),
  `resolved_at IS NOT NULL` means resolved (`comment_threads`), and
  `archived_at IS NOT NULL` means archived (`projects`,
  `conversations`).
- **Actor columns** (`created_by`, `performed_by`, `author`) hold the user
  email or the service account slug, the same as the graph does today.
- **Expressions.** `deploy` compares `CHECK`, `WHERE`, trigger `WHEN`,
  policy expressions, and function bodies as text. Write each one the way
  PostgreSQL and `pull` report it, with its parentheses and casts, or
  `deploy` sees a change on every run. PostgreSQL adds a cast to the base
  type for a domain column, for example `((slug)::text ~ ...)`. `pull`
  reformats a SQL function body, for example with a leading space and a
  trailing semicolon.
- **Fill factor.** The ten tables whose rows the application updates
  (`api_keys`, `conversations`, `deployments`, `identity_connections`,
  `issued_tokens`, `project_environments`, `project_promotions`,
  `project_syncs`, `projects`, `releases`) have `fillfactor = 90`. The
  data migration fills every page, and without free space the first
  UPDATE of a row cannot be a HOT update. 90 is a starting value: the
  rehearsal (plan WP3.2) reads `n_tup_hot_upd / n_tup_upd`.

## Delete behavior

- **Organizations, teams, environments, and project types** cannot be
  deleted while other rows refer to them (RESTRICT). A RESTRICT foreign
  key raises SQLSTATE 23001 (`restrict_violation`), and a foreign key
  with no delete action raises 23503 (`foreign_key_violation`). The API
  returns 409 for both. This includes the rows that restrict a template
  or a scoring policy to a project type: removing the last one would
  open the template or the policy to all project types. A team that
  manages an integration (`integrations.team_id`) is also RESTRICT.
- **Optional references** use `ON DELETE SET NULL (x_id)`
  (`on_delete_columns`), which clears only that column and keeps
  `organization_id`: `deployments.release_id`,
  `project_environments.current_release_id`, `roles.parent_role_id`, and
  the capability `identity_integration_id`. Two references are plain
  `SET NULL`, because their column is the whole foreign key:
  `analysis_reports.triggered_by` (to `users`) and
  `webhooks.identity_integration_id` (to `integrations`, which can be the
  instance sign-in provider). `webhooks.integration_id` is RESTRICT,
  because the `selectors_need_integration` check needs it.
- **A user or service account delete** fires `delete_principal()`, which
  deletes the principal. Its memberships, team memberships, API keys,
  tokens, client credentials, identity connections, and access grants
  cascade away. Content stays: actor columns hold names, and
  `documents.user_id` becomes NULL, so a personal document stays with no
  attachment. Assistant conversations of the user are deleted.
- **Embeddings** go with their entity. `delete_embeddings()` runs AFTER
  DELETE on the 17 embedded tables, also when a cascade deletes the row,
  so search cannot find deleted text. It is SECURITY DEFINER, owned by
  `imbi_trigger`, for two reasons. A row trigger that a cascade fires
  runs as the owner of the child table (`imbi_owner`), under FORCE ROW
  LEVEL SECURITY and with no organization setting, so an invoker
  function would delete nothing. And `imbi_admin` has no grant on
  `embeddings`, so it could not delete the sign-in provider. The function
  deletes only the rows with the deleted row's `node_label` and id, and
  it raises an error unless it runs as an AFTER DELETE row trigger with
  one argument. `PUBLIC` cannot execute it, so only the owner of a table
  or a superuser can attach it to a table. `TRUNCATE` does not fire
  delete triggers: the data migration loads `embeddings` itself.
- **Plugin edges** go with both ends. A composite foreign key from
  `plugin_edges.target_id` to `plugin_entities` deletes the edges of a
  deleted entity. `delete_plugin_edges()` runs AFTER DELETE on
  `environments` and deletes the edges whose source is the deleted
  environment. It is SECURITY DEFINER, owned by `imbi_trigger`, with the
  same guard, for the same reason as `delete_embeddings()`: no foreign
  key cascades into `environments` today, but a later one would fire the
  trigger as `imbi_owner` under row-level security with no organization
  setting. Plugin load accepts a manifest only when every `to_labels`
  entry is a plugin entity type and every `from_labels` entry is a core
  type whose table has this trigger (today only `Environment`).
- **The shared catalog** cannot be deleted from under an organization:
  the overlay and override tables refer to it with RESTRICT, and only
  `imbi_maintenance` can delete catalog rows.

## Row-level security

Each organization-scoped table has `ENABLE` and `FORCE ROW LEVEL SECURITY`
and this policy for all commands:

```sql
(organization_id = ( SELECT public.current_organization_id() AS current_organization_id))
```

`current_organization_id()` returns
`NULLIF(current_setting('imbi.organization_id', true), '')`, and
`current_principal_id()` does the same for `imbi.principal_id`. Both are
`STABLE` SQL functions with a SQL-standard body, so `search_path` cannot
change what they call. The scalar subquery makes the value an InitPlan:
PostgreSQL computes it once per statement, not once per row, and it is
still an index condition on `organization_id`.

The repository layer starts a transaction and then sets the context, each
setting in its own statement, before any read:

```sql
BEGIN;
SELECT set_config('imbi.organization_id', %s, true);
SELECT set_config('imbi.principal_id', %s, true);
```

The third argument makes a setting local to the transaction, so it cannot
stay on a pooled connection. When the organization setting is missing, a
policy matches no rows. It does not raise an error.

| Context | Settings | Used by |
|---|---|---|
| Organization | `imbi.organization_id`, and `imbi.principal_id` when there is a principal | every route under `/organizations/{org_slug}` |
| Principal only | `imbi.principal_id` | the organization switcher; `memberships` and `organizations` have SELECT policies for it that apply only while `imbi.organization_id` is not set |
| None | none | login; the `integrations` rows with no organization are readable |
| Instance admin | the `imbi_admin` login, no settings | reads and writes the instance sign-in providers (`instance_admin` policy); no organization rows, whatever it sets |

Other policies:

- `conversations` and `messages` have a RESTRICTIVE `owner_only` policy.
  Only the user in `imbi.principal_id` can read or write a conversation,
  and a message only with its conversation.
- The principal policies on `memberships` (`own_memberships`) and
  `organizations` (`principal_memberships`) apply only while
  `imbi.organization_id` is not set. In an organization context they
  would otherwise OR with the isolation policy, and a query without an
  organization condition would return the caller's rows in every
  organization.
- `organization_isolation` on `integrations` names the role `imbi_app`,
  so `imbi_admin` reaches only the NULL-organization rows through
  `instance_admin`.

Lookups before an organization is known use SECURITY DEFINER functions.
Each returns only what its caller needs. They run as `imbi_definer`, with
qualified names and `search_path = pg_temp`. That setting gives the
order `pg_catalog`, then `pg_temp`: PostgreSQL searches `pg_catalog`
first when the path does not name it, and searches a named `pg_temp` in
its place. Without it, `pg_temp` is searched first, and a temporary type
that `imbi_app` creates can shadow a catalog type in the function body
and run code as `imbi_definer`. (`pg_catalog, pg_temp` is the usual
form, but pglifecycle writes it as one quoted schema name; see Known
problems.) `check_integration_scope()` and `delete_embeddings()` use the
same setting. `PUBLIC` cannot execute the lookup functions; `imbi_app`
can.

| Function | Caller |
|---|---|
| `principal_permissions()` | authentication: the permissions of the principal over all memberships, with the role parent chain |
| `principal_memberships()`, `principal_teams()` | `GET /users/me` and the organization switcher |
| `webhook_organization_id(text)` | the gateway, for `POST /notifications/{id}` |
| `upload_organization_id(text)` | `GET /uploads/{id}`, before the membership check |
| `integration_organization_id(text)` | the identity connection routes |

`identity_connections.organization_id` holds the organization of the
integration, so the refresh sweeper sets the context from the row. A
trigger (`check_integration_scope`) keeps it equal to the organization of
the integration. The same trigger checks that a webhook identity pin names
an integration of the organization or the instance sign-in provider.

Threat model: RLS protects against a query that omits the organization
predicate. It does not protect against SQL injection or any other
arbitrary SQL on the `imbi_app` connection, because that SQL can call
`set_config` itself. SQL on `imbi_app` cannot switch to `imbi_admin`.

## Table map

`registry.toml` has the scope of every table: 55 organization, 2 tenancy,
13 instance, 4 catalog. The schema has 62 policies, 67 triggers, and 139
foreign keys.

| Area | Tables | Graph source |
|---|---|---|
| Tenancy | `tenants`, `organizations` | new; `Organization` |
| Organization structure | `teams`, `environments`, `project_types`, `link_definitions`, `tags` | vertex labels of the same name |
| Projects | `projects`, `project_type_assignments`, `project_environments`, `project_dependencies`, `project_syncs`, `project_promotions` | `Project`; `OWNED_BY` (as `projects.team_id`), `TYPE`, `DEPLOYED_IN`, `DEPENDS_ON`; the `*_sync_*` and `promote_*` vertex properties |
| Identity | `principals`, `users`, `service_accounts`, `memberships`, `team_members` | `User`, `ServiceAccount`; `MEMBER_OF` to Organization and to Team |
| RBAC | `roles`, `role_grants`, `permissions`, `resource_acls` | `Role`, `Permission`; `GRANTS`, `INHERITS_FROM` (as `roles.parent_role_id`), `CAN_ACCESS` |
| Credentials | `issued_tokens`, `totp_secrets`, `api_keys`, `client_credentials`, `oauth_clients`, `identity_connections`, `password_reset_tokens`, `local_auth_settings` | `TokenMetadata`, `TOTPSecret`, `APIKey`, `ClientCredential`, `OAuthClient`, `IdentityConnection`, `PasswordResetToken`, `LocalAuthConfig`; `HAS_IDENTITY` (as `identity_connections.user_id`), `ISSUED_TO` (as `issued_tokens.principal_id`), `MFA_FOR` (as `totp_secrets.user_id`), `OWNED_BY` (as `api_keys.principal_id` and `client_credentials.service_account_id`) |
| Delivery | `releases`, `deployments`, `blockers` | `Release`, `Deployment`, `Blocker`; `HAS_RELEASE`, `HAS_DEPLOYMENT`, `TARGETS`, `BLOCKED_BY`, and `BELONGS_TO` from Deployment to Project |
| SBOM catalog (shared) | `components`, `component_releases`, `component_identifiers`, `advisories` | `Component`, `ComponentRelease`, `ComponentIdentifier`, `Advisory`; `HAS_RELEASE` (as `component_releases.component_id`), `IDENTIFIED_BY` (as `component_identifiers.component_id`) |
| SBOM overlays (per organization) | `component_governance`, `component_release_governance`, `component_notes`, `component_advisories`, `component_overrides`, `component_release_overrides` | `status*` properties, `ComponentNote`, `HAS_NOTE` (as `component_notes.component_release_id`), `HAS_ADVISORY`; the overrides are new |
| Documents | `documents`, `document_tags`, `document_likes`, `document_templates`, `template_project_types`, `template_tags`, `comment_threads`, `comments`, `uploads` | `Document`, `DocumentTemplate`, `CommentThread`, `Comment`, `Upload`; `ATTACHED_TO`, `TAGGED_WITH`, `LIKED`, `ON_DOCUMENT`, `IN_THREAD` |
| Integrations | `integrations`, `project_integrations`, `project_capabilities`, `project_type_capabilities`, `webhooks`, `webhook_rules`, `plugin_registrations` | `Integration`, `Webhook`, `WebhookRule`, `PluginRegistration`; `EXISTS_IN`, `USES`, `MANAGED_BY`, `IMPLEMENTED_BY`, `ACTIONS` |
| Plugin data | `plugin_entities`, `plugin_entity_keys`, `plugin_edges` | manifest labels such as `AwsAccount`, and edges such as `MAPS_TO` |
| AI | `ai_providers`, `ai_models`, `ai_model_teams`, `mcp_servers`, `conversations`, `messages` | `AIProvider`, `AIModel`, `MCPServer`, `Conversation`, `Message`; `SERVED_BY`, `ALLOWED_FOR`, `CONTAINS` (as `messages.conversation_id`) |
| Analysis and scoring | `analysis_reports`, `analysis_results`, `blueprints`, `scoring_policies`, `scoring_policy_targets` | `AnalysisReport`, `AnalysisResult`, `Blueprint`, `ScoringPolicy`; `HAS_ANALYSIS_REPORT`, `HAS_RESULT`, `TARGETS` |
| Search | `embeddings` | existing `public.embeddings`, with `organization_id` added |

Not carried over:

- `Session`, `WebhookImplementation`, and `PERFORMED`: no code writes
  them. Code only deletes `Session` nodes. `SESSION_FOR` goes with
  `Session`.
- `OAuthIdentity` and `OAUTH_IDENTITY`: no code writes them, but
  `user_activity.py` still reads them. Count the nodes in production
  before the migration; see the review, section H.
- The `deployments` arrays on `DEPLOYED_TO`: #277 converted them into
  Deployment nodes. 61 arrays remain, on Releases that no Project owns;
  those Releases cannot be stored, because `releases.project_id` is NOT
  NULL.
- `USES_COMPONENT_RELEASE`: written but never read. ClickHouse
  `release_components` has the usage data, so its writer is deleted.
- `public.embedding_distance(agtype, ...)`: the graph initializer makes
  it at every start, and nothing calls it. Drop it with AGE.
- Organization-owned login providers: only the instance sign-in provider
  can have `used_as_login`.
- `Component` and `Role` embeddings. The UI cannot open a component
  search hit, and every search is scoped to the node ids of one
  organization, which never included the global graph roles. Search no
  longer embeds either type, so every `embeddings` row has an
  organization.
- `Tag.icon`: `Tag` inherits `icon` from `Node`, but no endpoint writes
  it. The data migration logs a value that is not NULL.
- `User.is_service_account`: no column yet. Plan O6 decides after the
  audit (plan Appendix E, E6) counts the users that set it.

`HAS_CONVERSATION` becomes `conversations.user_id`. The scheduler tables
stay in the `scheduler` schema until they move into this project.

## Differences from the evaluation

These are design decisions to review:

1. **Documents** have three nullable references (`project_id`,
   `project_type_id`, `user_id`) and
   `CHECK (num_nonnulls(...) <= 1)`, not three per-target join tables.
   The code attaches a document to one target and never moves it. A
   document of a deleted user has no attachment, as in the graph.
2. **Organization slugs are unique for the instance**, not per tenant.
   URLs are `/organizations/{slug}` and carry no tenant, so a per-tenant
   slug could not be routed. Change the constraint to
   `(tenant_id, slug)` when the tenant is part of the URL.
3. **Service accounts are instance-level**, like users. Access to an
   organization comes only from `memberships`. Authentication finds the
   account before any organization is known, so the table cannot use RLS.
4. **Role inheritance** is the column `roles.parent_role_id`, not a
   join table, because a role has at most one parent. A recursive CTE
   with `UNION` stops on a cycle, so a cycle cannot loop. No constraint
   prevents one.
5. **SBOM overlays are per organization.** In the graph, governance
   marks, notes, and `HAS_ADVISORY` edges are on the shared `Component`
   and `ComponentRelease` nodes, so they are global. A mark, note, or
   advisory that one organization records shows for every organization
   that uses the package, and any of those organizations can change or
   delete it. The schema gives each organization its own rows. The
   advisory itself (`advisories`, one row per CVE or GHSA id) stays
   shared, but holds only the id; `url` and `title` are in
   `component_advisories`, per organization and version.
6. **The shared catalog keeps the first values.** `imbi_app` can insert
   catalog rows but cannot change or delete them. When an SBOM of an
   organization has other values than the catalog row (name,
   description, license, supplier, hashes), SBOM ingest writes them to
   `component_overrides` or `component_release_overrides` for that
   organization. Readers use an override value where it is not NULL.
   The first component that claims an identifier keeps it.
7. **Project background-job state** is in `project_syncs` and
   `project_promotions`, not in about 30 columns on `projects`. Workers
   then do not update the same row that users edit.
8. **Scoring policy parameters** are one JSONB column. A `CHECK` on
   `category` requires the key fields with non-null values. The scoring
   models still validate the full shape.
9. **Plugin manifest indexes** are rows in `plugin_entity_keys`, not
   indexes that the application creates at runtime, so pglifecycle
   manages every index.
10. **No per-row blueprint version.** The evaluation asks for one, but
    no code maintains `Blueprint.version` today, so the column would stay
    empty. Add it with the code that writes it.
11. **No GIN index on `attributes`.** The evaluation (D9) asks for one,
    but row-level security stops `imbi_app` from using it (see
    Conventions).
12. **`password_reset_tokens.token_hash`** stores a hash of the token,
    not the token. The application must hash the token before it stores
    or looks up a row.
13. **No `revoked`, `resolved`, or `archived` booleans.** The graph keeps
    a boolean and a timestamp for each of these states. The schema keeps
    only the timestamp, so the two values cannot disagree. The
    application must test `*_at IS NOT NULL`, and the API can still
    return the boolean.
14. **Every slug column is validated,** except the Doctor result slug.
    Today `Node.slug` has no format check. Before the data migration,
    find the slugs that the `slug` domain rejects, grouped by label, and
    fix them or change the domain.
15. **Deletes fail where the graph cascades.** Organization, team,
    environment, and project type deletes are RESTRICT (see Delete
    behavior). In the graph they are DETACH DELETE.
16. **Routes move under the organization.** `/roles`, `/blueprints`,
    `/scoring/policies`, `/mcp-servers`, the plugin entity routes,
    `POST /uploads`, and the assistant conversation routes read or write
    organization tables, so they move under `/organizations/{org_slug}`.
    This changes the API and the UI.
17. **`issued_tokens` has no nanoid.** Its primary key is `jti`. Every
    token query finds the row by `jti`, the family, or the principal, and
    the graph `id` exists only because every graph model has one. One
    unique index fewer on the busiest instance table.

## Known problems

Tested with the pinned pglifecycle commit (see Tool), against
PostgreSQL 18.3 with pgvector 0.8.2.

1. **Function return types must be lower case.** `deploy` compares a
   function's `returns` as text, so `TEXT` does not match `text` and each
   deploy runs `CREATE OR REPLACE FUNCTION`. A `pg_catalog.` qualifier in
   the body has the same effect. The function files use the form that
   `pull` writes. Column and domain types can be upper case: a second
   deploy is empty except for item 2.
2. **The HNSW expression index changes on every deploy.** `pull` records
   the expression as `(embedding)::vector(384)`. `build` and `deploy`
   write it without the outer parentheses, and PostgreSQL rejects that
   form. The project keeps `((embedding)::vector(384))`, which creates
   correctly but never matches.
3. **A SQL function body is checked when the function is created.**
   `deploy` creates functions before tables, so each SECURITY DEFINER
   function lists the tables it reads under `dependencies`. It also
   lists the functions it calls, by name only
   (`public.current_principal_id`). `build` does not find an entry with
   an argument list: it skips the entry with a warning, and the order of
   the names then decides.
4. **The HNSW index has a fixed dimension** (384, for the default
   `BAAI/bge-small-en-v1.5` model). Today the application creates it at
   startup from settings. A different model needs a change to this
   project.
5. **Storage parameter values must be strings.** `pull` reports
   `fillfactor: '90'`. An integer `90` does not match, and each deploy
   drops and creates the table.
6. **A list setting cannot be written.** `deploy` writes a function
   `configuration` value as one quoted string, so
   `search_path: pg_catalog, pg_temp` becomes the single schema name
   `"pg_catalog, pg_temp"`, and a YAML list becomes `ARRAY[...]`, which
   `SET` rejects. The functions use `search_path: pg_temp`, which gives
   the same order (see Row-level security).

## Open questions

1. Existing rows have no organization for these tables: `uploads`,
   `conversations`, `messages`, `mcp_servers`, `blueprints`,
   `scoring_policies`, `roles`, `plugin_entities`, the SBOM overlay
   tables (see Differences item 5), and documents attached to a user.
   With one organization in production, the ETL can assign it. Is that
   acceptable?
2. Private SBOM packages are not modeled. They change identifier
   uniqueness, visibility, and advisory matching.
3. Should `documents.user_id` require a membership of that user in the
   document's organization? A foreign key to `memberships` would delete
   the document when the membership is removed.
4. Should actor columns also store a principal id, for audit, next to
   the email or slug?
5. Should `imbi_app` have narrower privileges on secret columns
   (`totp_secrets`, `api_keys.key_hash`, token ciphertexts)?
6. Tenant-level settings from the evaluation (OIDC providers, SMTP, LLM
   and Slack credentials) are not modeled. They are separate work.
7. Deleting an identity integration clears a capability
   `identity_integration_id`, so the call then uses the integration
   credentials, not the acting user's. Is that acceptable, or should the
   delete fail?
