-- Behavior tests T1 to T20 of the second schema review, as pgTAP.
--
-- Converted from the meta repository
-- docs/age-to-relational-schema-review/second-review/apply/behavior.sql,
-- which only printed its results. The expected values come from the
-- comments of that file and from its accepted output, behavior6.out.
-- Where the source ran owners.sql first, deploy now sets the owners,
-- and T13 checks them.
--
-- root:schema-check runs this file as postgres, in a new copy of the
-- deployed database, with pgTAP in the schema tap. Other roles get
-- access to the pgTAP temporary tables after plan(). The file does not
-- call finish(): a ROLLBACK removes the pgTAP state of the tests in it,
-- so root:schema-check reads the TAP output instead.
SET search_path = public, tap;
SELECT plan(43);
GRANT ALL ON ALL TABLES IN SCHEMA pg_temp TO PUBLIC;
GRANT ALL ON ALL SEQUENCES IN SCHEMA pg_temp TO PUBLIC;

INSERT INTO tenants (id, name, slug) VALUES ('t1', 'T', 't');
INSERT INTO organizations (id, tenant_id, name, slug)
VALUES ('oA', 't1', 'A', 'a'), ('oB', 't1', 'B', 'b');
INSERT INTO principals (id, principal_type) VALUES ('u1', 'user');
INSERT INTO users (id, email, display_name)
VALUES ('u1', 'u1@example.com', 'U1');
INSERT INTO roles (id, organization_id, name, slug)
VALUES ('rA', 'oA', 'R', 'r'), ('rB', 'oB', 'R', 'r');
INSERT INTO memberships (organization_id, principal_id, role_id)
VALUES ('oA', 'u1', 'rA'), ('oB', 'u1', 'rB');
INSERT INTO teams (id, organization_id, name, slug)
VALUES ('tm1', 'oA', 'Team', 'team');
INSERT INTO projects (id, organization_id, team_id, name, slug)
VALUES ('p1', 'oA', 'tm1', 'P', 'p');
INSERT INTO releases (id, organization_id, project_id, committish, title,
                      created_by)
VALUES ('r1', 'oA', 'p1', 'abcdef0', 'R', 'x@example.com');
INSERT INTO plugin_registrations (slug, enabled)
VALUES ('aws', true), ('github', true);
INSERT INTO integrations (id, organization_id, team_id, plugin_slug, name,
                          slug)
VALUES ('iA', 'oA', NULL, 'github', 'GH A', 'gh-a'),
       ('iB', 'oB', NULL, 'github', 'GH B', 'gh-b'),
       ('iS', NULL, NULL, 'github', 'Sign in', 'sign-in');
INSERT INTO environments (id, organization_id, name, slug)
VALUES ('e1', 'oA', 'Prod', 'prod');
INSERT INTO plugin_entities (id, organization_id, plugin_slug, label)
VALUES ('pe1', 'oA', 'aws', 'AwsAccount'), ('pe2', 'oA', 'aws', 'AwsAccount');
INSERT INTO embeddings (organization_id, node_label, node_id, attribute,
                        chunk_text, embedding)
VALUES ('oA', 'Project', 'p1', 'name', 'P',
        array_fill(0.1, ARRAY[384])::vector),
       ('oA', 'Release', 'r1', 'title', 'R',
        array_fill(0.1, ARRAY[384])::vector),
       ('oA', 'Integration', 'iS', 'name', 'S',
        array_fill(0.1, ARRAY[384])::vector);

-- T1 A1
SELECT throws_ok($$DELETE FROM teams WHERE id = 'tm1'$$, '23001', NULL,
                 'T1 a team with a project cannot be deleted (RESTRICT)');

-- T2 A1
INSERT INTO teams (id, organization_id, name, slug)
VALUES ('tm2', 'oA', 'T2', 't2');
UPDATE integrations SET team_id = 'tm2' WHERE id = 'iA';
SELECT throws_ok($$DELETE FROM teams WHERE id = 'tm2'$$, '23001', NULL,
                 'T2 a team that manages an integration cannot be deleted');
UPDATE integrations SET team_id = NULL WHERE id = 'iA';

-- T3 A2
DELETE FROM projects WHERE id = 'p1';
SELECT results_eq(
  $$SELECT node_label, node_id::text COLLATE "default"
      FROM embeddings ORDER BY 1$$,
  $$VALUES ('Integration', 'iS')$$,
  'T3 a cascaded delete with no organization setting removes the '
  'Release embedding');

-- T4 A2 and D5
SET ROLE imbi_admin;
WITH deleted AS (DELETE FROM integrations WHERE id = 'iS' RETURNING 1)
SELECT is(count(*)::int, 1, 'T4 imbi_admin deletes the sign-in provider')
  FROM deleted;
RESET ROLE;
SELECT is((SELECT count(*) FROM embeddings)::int, 0,
          'T4 the sign-in provider embedding is gone');

-- T5 D5
BEGIN;
SET LOCAL ROLE imbi_admin;
SET LOCAL imbi.organization_id = 'oA';
SELECT is((SELECT count(*) FROM integrations
            WHERE organization_id IS NOT NULL)::int, 0,
          'T5 imbi_admin with an organization set sees no organization '
          'integrations');
WITH changed AS (
  UPDATE integrations SET name = 'x' WHERE id = 'iA' RETURNING 1)
SELECT is(count(*)::int, 0,
          'T5 imbi_admin cannot update an organization integration')
  FROM changed;
ROLLBACK;

-- T6 A6
BEGIN;
SET LOCAL ROLE imbi_app;
SET LOCAL imbi.organization_id = 'oA';
SET LOCAL imbi.principal_id = 'u1';
SELECT is((SELECT count(*) FROM memberships)::int, 1,
          'T6 in organization oA the principal sees one membership');
SELECT is((SELECT count(*) FROM organizations)::int, 1,
          'T6 in organization oA the principal sees one organization');
ROLLBACK;

-- T7 A6
BEGIN;
SET LOCAL ROLE imbi_app;
SET LOCAL imbi.principal_id = 'u1';
SELECT is((SELECT count(*) FROM memberships)::int, 2,
          'T7 with no organization the principal sees both memberships');
SELECT is((SELECT count(*) FROM organizations)::int, 2,
          'T7 with no organization the principal sees both organizations');
ROLLBACK;

-- T8 A7
SET ROLE imbi_app;
SELECT throws_ok(
  $$INSERT INTO tenants (id, name, slug) VALUES ('t2', 'T2', 't2')$$,
  '42501', NULL, 'T8 imbi_app cannot insert a tenant');
RESET ROLE;

-- T9 D10
INSERT INTO plugin_edges (organization_id, plugin_slug, edge_type,
                          source_label, source_id, target_label, target_id)
VALUES ('oA', 'aws', 'MAPS_TO', 'Environment', 'e1', 'AwsAccount', 'pe1');
INSERT INTO environments (id, organization_id, name, slug)
VALUES ('e2', 'oA', 'Stage', 'stage');
INSERT INTO plugin_edges (organization_id, plugin_slug, edge_type,
                          source_label, source_id, target_label, target_id)
VALUES ('oA', 'aws', 'MAPS_TO', 'Environment', 'e2', 'AwsAccount', 'pe2');
DELETE FROM environments WHERE id = 'e1';
SELECT is((SELECT count(*) FROM plugin_edges)::int, 1,
          'T9 an environment delete removes its edges');
DELETE FROM plugin_entities WHERE id = 'pe2';
SELECT is((SELECT count(*) FROM plugin_edges)::int, 0,
          'T9 an entity delete removes the edges to it');

-- T10 D10
SELECT throws_ok(
  $$INSERT INTO plugin_edges (organization_id, plugin_slug, edge_type,
                              source_label, source_id, target_label,
                              target_id)
    VALUES ('oA', 'aws', 'MAPS_TO', 'Environment', 'e2', 'AwsAccount',
            'nope')$$,
  '23503', NULL, 'T10 an edge to a missing entity is rejected');

-- T11 D2
SELECT throws_ok(
  $$INSERT INTO embeddings (organization_id, node_label, node_id, attribute,
                            chunk_text, embedding)
    VALUES (NULL, 'Component', 'c1', 'name', 'C',
            array_fill(0.1, ARRAY[384])::vector)$$,
  '23502', NULL, 'T11 an embedding without an organization is rejected');

-- T12 D9
SELECT col_is_pk('public', 'issued_tokens', 'jti',
                 'T12 the primary key of issued_tokens is jti');
SELECT hasnt_column('public', 'issued_tokens', 'id',
                    'T12 issued_tokens has no id column');

-- T13 A2 and A3
SELECT results_eq(
  $$SELECT p.proname::text COLLATE "default", p.prosecdef,
           pg_get_userbyid(p.proowner)::text COLLATE "default",
           p.proconfig::text COLLATE "default"
      FROM pg_proc AS p
     WHERE p.pronamespace = 'public'::regnamespace
       AND (p.prosecdef
            OR p.proname IN ('check_integration_scope',
                             'delete_plugin_edges'))
     ORDER BY 1$$,
  $$VALUES
      ('check_integration_scope', false, 'imbi_owner',
       '{search_path=pg_temp}'),
      ('delete_embeddings', true, 'imbi_trigger', '{search_path=pg_temp}'),
      ('delete_plugin_edges', true, 'imbi_trigger', '{search_path=pg_temp}'),
      ('integration_organization_id', true, 'imbi_definer',
       '{search_path=pg_temp}'),
      ('principal_memberships', true, 'imbi_definer', '{search_path=pg_temp}'),
      ('principal_permissions', true, 'imbi_definer', '{search_path=pg_temp}'),
      ('principal_teams', true, 'imbi_definer', '{search_path=pg_temp}'),
      ('upload_organization_id', true, 'imbi_definer',
       '{search_path=pg_temp}'),
      ('webhook_organization_id', true, 'imbi_definer',
       '{search_path=pg_temp}')$$,
  'T13 function security, owner and search_path');

-- T14 A2
SELECT ok(NOT has_function_privilege('imbi_app', 'public.delete_embeddings()',
                                     'EXECUTE'),
          'T14 PUBLIC has no EXECUTE on delete_embeddings()');

-- T15 D8. The source also printed the number of C and default
-- columns; a new column changes those numbers, so only the two rules
-- are tested.
SELECT is_empty(
  $$SELECT table_name || '.' || column_name
      FROM information_schema.columns
     WHERE table_schema = 'public' AND collation_name IS DISTINCT FROM 'C'
       AND (column_name IN ('id', 'slug', 'jti')
            OR column_name LIKE '%\_id')
       AND udt_name IN ('text', 'slug')$$,
  'T15 every key column uses COLLATE "C"');
SELECT is_empty(
  $$SELECT table_name || '.' || column_name
      FROM information_schema.columns
     WHERE table_schema = 'public' AND collation_name = 'C'
       AND column_name IN ('name', 'title', 'description', 'purl_name',
                           'content', 'display_name', 'email')$$,
  'T15 no human text column uses COLLATE "C"');

-- T16 A8
SELECT is((SELECT count(*) FROM pg_class
            WHERE relkind = 'r'
              AND reloptions @> ARRAY['fillfactor=90'])::int, 10,
          'T16 ten tables have fillfactor 90');

-- T17 A5, A9 and A11. The accepted output has five of the eight names:
-- A5 dropped the other three.
SELECT hasnt_index('public', 'scoring_policies',
                   'scoring_policies_attribute_idx',
                   'T17 scoring_policies_attribute_idx is dropped (A5)');
SELECT hasnt_index('public', 'components', 'components_ecosystem_idx',
                   'T17 components_ecosystem_idx is dropped (A5)');
SELECT hasnt_index('public', 'deployments', 'deployments_in_flight_idx',
                   'T17 deployments_in_flight_idx is dropped (A5)');
SELECT is(pg_get_indexdef(to_regclass(name)), definition, 'T17 ' || name)
  FROM (VALUES
          ('public.document_likes_user_idx',
           'CREATE INDEX document_likes_user_idx ON public.document_likes '
           'USING btree (user_id)'),
          ('public.issued_tokens_principal_idx',
           'CREATE INDEX issued_tokens_principal_idx ON public.issued_tokens '
           'USING btree (principal_id, revoked_at)'),
          ('public.project_promotions_environment_idx',
           'CREATE INDEX project_promotions_environment_idx ON '
           'public.project_promotions USING btree (organization_id, '
           'environment_id) WHERE (environment_id IS NOT NULL)'),
          ('public.project_promotions_from_environment_idx',
           'CREATE INDEX project_promotions_from_environment_idx ON '
           'public.project_promotions USING btree (organization_id, '
           'from_environment_id) WHERE (from_environment_id IS NOT NULL)'),
          ('public.webhooks_identity_integration_idx',
           'CREATE INDEX webhooks_identity_integration_idx ON public.webhooks '
           'USING btree (identity_integration_id) '
           'WHERE (identity_integration_id IS NOT NULL)'))
       AS expected (name, definition)
 ORDER BY name;

-- T18 A12 and D7
SELECT col_type_is('public', 'ai_models', 'default_temperature',
                   'numeric(4,3)',
                   'T18 ai_models.default_temperature is numeric(4,3)');
SELECT col_type_is('public', 'ai_models', 'default_top_p', 'numeric(4,3)',
                   'T18 ai_models.default_top_p is numeric(4,3)');
SELECT col_type_is('public', 'conversations', 'archived_at',
                   'timestamp with time zone',
                   'T18 conversations.archived_at is timestamptz');
SELECT hasnt_column('public', 'conversations', 'archived',
                    'T18 conversations has no archived boolean');

-- T19 counts (README Table map)
SELECT is((SELECT count(*) FROM pg_tables
            WHERE schemaname = 'public')::int, 74, 'T19 74 tables');
SELECT is((SELECT count(*) FROM pg_policies
            WHERE schemaname = 'public')::int, 62, 'T19 62 policies');
SELECT is((SELECT count(*) FROM pg_trigger AS t
             JOIN pg_class AS c ON c.oid = t.tgrelid
            WHERE c.relnamespace = 'public'::regnamespace
              AND NOT t.tgisinternal)::int, 67, 'T19 67 triggers');
SELECT is((SELECT count(*) FROM pg_trigger AS t
            WHERE NOT t.tgisinternal
              AND t.tgfoid = 'public.delete_embeddings()'::regprocedure)::int,
          17, 'T19 17 embedding delete triggers');
SELECT is((SELECT count(*) FROM pg_constraint AS c
            WHERE c.connamespace = 'public'::regnamespace
              AND c.contype = 'f')::int, 139, 'T19 139 foreign keys');
SELECT is((SELECT count(*) FROM pg_class AS c
            WHERE c.relnamespace = 'public'::regnamespace
              AND c.relrowsecurity AND c.relforcerowsecurity)::int, 56,
          'T19 56 tables with forced row-level security');

-- T20 D10 hardening. The test adds a parent table in this copy of the
-- database only.
CREATE TABLE public.t20_parent (id text PRIMARY KEY);
ALTER TABLE public.environments
  ADD COLUMN t20_parent_id text REFERENCES public.t20_parent
             ON DELETE CASCADE;
INSERT INTO public.t20_parent VALUES ('tp');
UPDATE public.environments SET t20_parent_id = 'tp' WHERE id = 'e2';
INSERT INTO plugin_edges (organization_id, plugin_slug, edge_type,
                          source_label, source_id, target_label, target_id)
VALUES ('oA', 'aws', 'MAPS_TO', 'Environment', 'e2', 'AwsAccount', 'pe1');
SELECT is((SELECT count(*) FROM plugin_edges)::int, 1,
          'T20 the edge exists before the cascade');
DELETE FROM public.t20_parent WHERE id = 'tp';
SELECT is((SELECT count(*) FROM plugin_edges)::int, 0,
          'T20 an environment deleted by a cascade, with no organization '
          'setting, loses its edges');
