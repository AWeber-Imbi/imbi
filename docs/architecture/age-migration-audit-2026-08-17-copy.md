# Pre-migration audit: production copy of 2026-08-17

Plan: `meta:docs/age-to-relational-implementation-plan.md` WP1.9, for
WP3.0 and the decisions O3 to O6 and O10 (plan section 8).

This document has counts only. It has no personal data: no email, no
name, and no node id.

## Status: the counts are not measured

The audit did not run on the production copy. The agent session refused
the restore of `meta:backups/imbi.sql` into `prodcopy_20260817`, because
the backup holds personal data. Nothing was restored. The counts move to
gate G2: Gavin decides which copy the audit runs on. Every count in this
document is "not measured" until then.

The audit code ran on a synthetic graph and on the test database (the
tests in `libraries/common/tests/test_etl_audit.py`). It did not run on
production data.

## How to run it

On the scratch server, as a person who is permitted to restore the
backup:

1. Restore the backup into `prodcopy_20260817`, with the AGE catalog
   repair of the `meta:Justfile` recipe `restore-dev-postgres` (the
   graph oid rewrite, the missing labels, and the duplicate edge rows).
   Do not run the recipe itself: it writes to the dev cluster.
2. Clone the copy, and run the audit on the clone:

   ```bash
   psql -h 127.0.0.1 -p 55432 -U postgres \
     -c 'CREATE DATABASE e_copy TEMPLATE prodcopy_20260817'
   uv run python -m imbi.common.db.etl.audit audit \
     --source-url postgresql://postgres@127.0.0.1:55432/e_copy \
     --output audit-2026-08-17.json
   ```

   After the ETL command merges, the same command is
   `imbi-common etl audit`.
3. Keep the JSON file out of the repository: its `ids` are node ids.
   Copy only the counts into the tables below.

The command reads only. It sets its transaction read only, so it can
also run on production with a read-only login (a later step, with
Gavin).

## What the audit checks

| Kind | Rules | Source |
|---|---|---|
| Appendix E | 54 queries (some rules have one query for each label or part) | `db/etl/audit/appendix_e.py` |
| Schema | 1,447 rules for 68 tables: the type, NOT NULL, JSON text, domain, CHECK, UNIQUE, and foreign key rules | `db/etl/audit/checks.py`, from `schemata/` through `tables.py` |

For each table, a source query gives the rows that the ETL would insert
(`db/etl/audit/sources.py`). The schema rules run on these rows. The
property names come from the code that writes each label.

The audit reports a schema rule that the source rows cannot show as
"not covered", with the reason:

| Table | Not covered | Reason |
|---|---|---|
| `tenants` | all | no graph source: the ETL creates one row (E2) |
| `organizations` | `tenant_id` NOT NULL and FK | the ETL sets it (E2) |
| `document_templates`, `template_project_types`, `template_tags` | the template id and the rules on it | the ETL makes new ids (E22) |
| `component_overrides`, `component_release_overrides` | all | new tables, no graph source |
| `plugin_entity_keys` | all | the ETL makes the rows from the plugin manifests |
| `resource_acls` | all | no code writes `CAN_ACCESS` |
| `embeddings` | the schema rules | E28, E29, and E32 check `public.embeddings` |

## Counts for the open decisions

| Decision | Audit rule | Count | Recommendation (plan section 8) |
|---|---|---|---|
| O3 email case | E5: users whose email differs from another user email only in case | not measured | Store lower case, with `CHECK (email = lower(email))` and a plain UNIQUE. E5.not_lower counts the emails that the ETL must change to lower case. If E5 is not zero, merge those users first (no API path; see E5 below). |
| O4 `identity_connections` UNIQUE `(integration_id, subject)` | E11 | not measured | No recommendation in the plan. If E11 is zero, keep the constraint and map 23505 to 409. |
| O5 `OAuthIdentity` | E13: `OAuthIdentity` nodes | not measured | No recommendation in the plan. If E13 is zero, delete the two reads in `user_activity.py`. |
| O6 `is_service_account` | E6: users with `is_service_account` | not measured | No recommendation in the plan. If E6 is zero, remove the flag from the API. |
| O10 Releases with no Project | E15.Release | not measured (#277 reported 61) | Accepted (D29): skip them and list them in the reconciliation report. E15.Release.DEPLOYED_TO counts the #277 set among them. |

## Blocking rules and their repair path (WP3.0)

"API" means a normal application write. "Direct write" means a graph
write that needs Gavin's approval (WP3.0, step 3).

| Rule | Count | Repair path |
|---|---|---|
| E1 more than one Organization | not measured | API: `DELETE /organizations/{slug}` (`endpoints/organizations.py:643`), UI: yes. The delete does not cascade: the children of the organization stay as orphans. Delete each child first through its own endpoint. A merge of two organizations needs a direct write. |
| E3 duplicate slugs in one organization (schema UNIQUE rules on `(organization_id, slug)`) | not measured | Webhooks, AI providers, AI models, and MCP servers: API by id. Link definitions and teams: the API writes by slug too, but the graph has unique slug indexes for them. Scoring policies and blueprints: no rename (DELETE plus POST). The graph has unique slug indexes for Team, LinkDefinition, MCPServer, Role, ScoringPolicy, Integration, Webhook, and ServiceAccount; if they exist in production, these labels have no duplicates. |
| E39 duplicates that the API cannot split: environments, project types, tags, document templates | not measured | No API path: the API addresses these rows by slug, so a PATCH writes to both duplicates and a DELETE removes both. WP3.0 repairs them with a direct write by id (`SET x.slug`), each with Gavin's approval. |
| E38.release_tag Releases whose tag is `''` | not measured | API: `PATCH` of the release (`endpoints/releases.py:1210`) with a new `/tag`. The PATCH does not normalize `''`, so check the value that it writes. || E4 slugs that the `slug` domain or a slug CHECK rejects | not measured | Projects: API (`PATCH /organizations/{org}/projects/{id}`, `/slug`), UI: yes. A slug change sends a lifecycle event, and plugins can rename the remote repository. Organizations: API and UI. Webhooks: API and UI; a PATCH must replace `/slug` in the same patch. Integrations: no API path (a slug change is ignored); DELETE plus POST loses the connections and edges, so use a direct write. Service accounts: no API path (400); direct write. Roles: the PATCH makes a copy of the node (a defect); direct write, and update `MEMBER_OF.role`. |
| E5 emails that differ only in case | not measured | No API path to change an email or to merge users. `DELETE /users/{email}` removes one user and leaves its identity connections and conversations. A merge needs a direct write. |
| E6 users with `is_service_account` | not measured | API: `PATCH /users/{email}` with `replace /is_service_account false`. UI: no (the list hides these users). O6 decides first. |
| E8 projects with no `OWNED_BY` team | not measured | No API path. Every project route matches through `OWNED_BY`, so such a project returns 404. Direct write: create the `OWNED_BY` edge. Then the normal team change works. |
| E11 duplicate `(integration_id, subject)` | not measured | API, self-service only: `DELETE /me/identities/{integration_id}`, called twice by the owning user. No admin path. Direct write for other users. O4 decides first. |
| E13 `OAuthIdentity` nodes | not measured | No API path. Direct write, after O5. |
| E14 duplicate Releases | not measured (expected 0, D12) | No API path: the release routes have no DELETE. Direct write. |
| E20 more than one open blocker for one reference | not measured | API: `POST .../releases/{tag}/blockers/{id}/resolve` (`endpoints/project_deployments.py:7503`), UI: yes. Fix E8 first for that project. |
| E23 template project type slugs that name no live project type | not measured | API: `PATCH /organizations/{org}/document-templates/{slug}` with `replace /project_type_slugs`, UI: yes. |
| E24.slug `Integration.plugin` values that the slug domain rejects | not measured | No API path (`plugin` is not in the update model). Direct write. |
| E25 organization integrations with `used_as_login` | not measured | API: `PUT /organizations/{org}/integrations/{slug}/login-provider` with `{"used_as_login": false}`; UI: no. There is no API that moves users. Sign-in links a user by email to the existing row, so: create an instance sign-in provider (`POST /login-providers/`, UI: yes), make it the sign-in provider, then turn off the organization integration. The email match is case-sensitive (E5). |
| E26 webhook rule handlers that do not match the pattern | not measured | API: `PATCH /organizations/{org}/webhooks/{webhook}` with `replace /rules`, UI: yes. |
| E28 text-model embeddings without 384 dimensions | not measured | API: `POST /maintenance/operations/search-reindex/run`, UI: yes. A reindex does not delete the rows of deleted nodes (E29); delete those rows directly. |
| Schema type rules (a value that does not convert) | not measured | A PATCH writes the model again, so it repairs `updated_at` and the fields in the patch. No API changes `created_at`. For Team, Environment, ProjectType, and LinkDefinition, a `created_at` that does not parse makes each PATCH fail with 500. Direct write. |
| Schema NOT NULL rules (no default) | not measured | Add the value with a PATCH (`add /name`) where the model has the field. `organization_id` and `team_id` come from edges: see E1, E8, and the findings below. |

## Findings for the plan

These come from the code that writes each label. Gavin decided them on
2026-09-30; plan Appendix E records the decisions.

1. Nodes with no `id` (E36, new): the seeded `Organization` and system
   `Role`s, the setup admin `User` until its first sign-in, and every
   `WebhookRule`, `AnalysisResult`, and `PluginRegistration`. The ETL
   derives the id from the graph id. Not blocking. The audit gives such
   a node the stand-in id `gid:<graph id>`, so the rows that refer to it
   still join.
2. E10 is corrected: the boolean wins, because the AGE-era code reads
   it. A seeded internal-service credential can have `revoked = false`
   and a kept `revoked_at` (`auth/internal_services.py:283`, `:373`);
   "timestamp wins" would load it as revoked.
3. Orphan documents and comment threads (E37, new): a delete of a
   project, project type, user, or document leaves them. An orphan
   document gets the one organization and no target. An orphan comment
   thread is skipped, with its comments.
4. JSON text and `''` that E30 does not list (E38, new):
   `Project.links` and `identifiers`; the `Integration` `options`,
   `encrypted_credentials`, `capabilities`, `links`, and `identifiers`;
   `IdentityConnection.metadata`; the `AIModel` cost values as numeric
   text; and the `''` values of the four `set_status()` writers. The ETL
   parses them and writes NULL for `''`. `Release.tag = ''` is blocking.
5. E3 duplicates that the API cannot split (E39, new): see the repair
   table above.
6. The graph keeps the last SBOM values of a component, not the first,
   so `component_overrides` cannot come from the graph (README
   Differences 6).
7. `DocumentTemplate` ids are the slug, so two organizations can have
   the same template id.
8. This code still embeds `Component` and `Role` (`models.py:1113`,
   `:1120`; `Role` is a `Node`). D23 says that search no longer embeds
   them; WP2.10 must change the embedded set.
9. `Integration`, `Webhook`, `ScoringPolicy`, `PluginRegistration`, and
   `AwsAccount` have no `created_at`, so the column default applies.
10. The graph unique index of `IdentityConnection` is on
    `(plugin_id, user_id)`, but the writer uses `integration_id`
    (`graph/schemata.toml:252-254`, `identity/repository.py:120`). The
    graph does not enforce one connection per integration and user.
11. The Role PATCH with a new slug makes a second Role node with the same
    id (`endpoints/roles.py:366`), and an Integration PATCH ignores a
    slug change.
