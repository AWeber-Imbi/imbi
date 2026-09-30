-- Row-level security and review smoke tests, as pgTAP.
--
-- Converted from the meta repository
-- docs/age-to-relational-schema-review/rls_smoke.sql (first part) and
-- review_smoke.sql (second part), which ran in this order on one
-- database and only printed their results. The comment on each block
-- names its block in the source file.
--
-- root:schema-check runs this file as postgres, in a new copy of the
-- deployed database, with pgTAP in the schema tap. A statement that
-- SET ROLE runs as another role. pgTAP keeps its state in temporary
-- tables of this session, so the other roles get access to them after
-- plan(). A ROLLBACK also removes that state, so the file does not call
-- finish(): root:schema-check reads the TAP output, and fails on a
-- "not ok" line or on a test count that is not the plan.
SET search_path = public, tap;
SELECT plan(81);
GRANT ALL ON ALL TABLES IN SCHEMA pg_temp TO PUBLIC;
GRANT ALL ON ALL SEQUENCES IN SCHEMA pg_temp TO PUBLIC;

-- rls_smoke: seed as superuser (bypasses RLS)
INSERT INTO tenants (id, name, slug) VALUES ('t1', 'Tenant', 'tenant');
INSERT INTO organizations (id, tenant_id, name, slug)
VALUES ('orgA', 't1', 'A', 'a'), ('orgB', 't1', 'B', 'b');
INSERT INTO principals (id, principal_type) VALUES ('u1', 'user');
INSERT INTO users (id, email, display_name)
VALUES ('u1', 'u1@example.com', 'U1');
INSERT INTO roles (id, organization_id, name, slug)
VALUES ('rA', 'orgA', 'Admin', 'admin'), ('rB', 'orgB', 'Admin', 'admin');
INSERT INTO memberships (organization_id, principal_id, role_id)
VALUES ('orgA', 'u1', 'rA');
INSERT INTO teams (id, organization_id, name, slug)
VALUES ('tA', 'orgA', 'Team A', 'team'), ('tB', 'orgB', 'Team B', 'team');

SET ROLE imbi_app;

-- rls_smoke: no setting
SELECT is((SELECT count(*) FROM teams)::int, 0,
          'imbi_app with no setting sees no teams');
SELECT is((SELECT count(*) FROM organizations)::int, 0,
          'imbi_app with no setting sees no organizations');

-- rls_smoke: principal u1, no organization
BEGIN;
SELECT set_config('imbi.principal_id', 'u1', true);
SELECT results_eq('SELECT slug::text COLLATE "default" FROM organizations ORDER BY slug',
                  ARRAY['a'],
                  'the principal sees only the organization of its membership');
SELECT results_eq('SELECT organization_id::text COLLATE "default" FROM memberships',
                  ARRAY['orgA'],
                  'the principal sees only its own membership');
SELECT is((SELECT count(*) FROM teams)::int, 0,
          'the principal context shows no teams');
COMMIT;

-- rls_smoke: organization A
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT results_eq('SELECT id::text COLLATE "default" FROM teams', ARRAY['tA'],
                  'organization A sees only team A');
SELECT throws_ok(
  $$INSERT INTO teams (id, organization_id, name, slug)
    VALUES ('tX', 'orgB', 'X', 'x')$$,
  '42501', NULL,
  'a team of organization B cannot be inserted from organization A');
ROLLBACK;

-- rls_smoke: project in A that points at team B
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT throws_ok(
  $$INSERT INTO projects (id, organization_id, team_id, name, slug)
    VALUES ('p1', 'orgA', 'tB', 'P', 'p')$$,
  '23503', NULL,
  'a project cannot refer to a team of another organization');
ROLLBACK;

-- rls_smoke: valid project in A
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT lives_ok(
  $$INSERT INTO projects (id, organization_id, team_id, name, slug)
    VALUES ('p1', 'orgA', 'tA', 'P', 'p')$$,
  'a project of organization A can be inserted');
COMMIT;

-- rls_smoke: transaction-local setting does not leak
SELECT is((SELECT count(*) FROM projects)::int, 0,
          'the organization setting ends with its transaction');

-- rls_smoke: document with two attachments
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT throws_ok(
  $$INSERT INTO documents (id, organization_id, project_id, user_id, title,
                           content, created_by)
    VALUES ('d1', 'orgA', 'p1', 'u1', 'T', 'C', 'u1@example.com')$$,
  '23514', NULL,
  'a document cannot have two attachments');
ROLLBACK;

-- rls_smoke: role with a recursive parent chain
RESET ROLE;
INSERT INTO permissions (name, resource_type, action)
VALUES ('project:read', 'project', 'read'),
       ('project:write', 'project', 'write');
INSERT INTO roles (id, organization_id, name, slug, parent_role_id)
VALUES ('rA2', 'orgA', 'Child', 'child', 'rA');
INSERT INTO role_grants (organization_id, role_id, permission_name)
VALUES ('orgA', 'rA', 'project:read'), ('orgA', 'rA2', 'project:write');
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT results_eq(
  $$WITH RECURSIVE chain AS (
           SELECT r.id, r.parent_role_id
             FROM roles AS r
            WHERE r.id = 'rA2'
            UNION
           SELECT p.id, p.parent_role_id
             FROM roles AS p
             JOIN chain AS c
               ON p.id = c.parent_role_id)
    SELECT rg.permission_name::text COLLATE "default"
      FROM chain AS c
      JOIN role_grants AS rg
        ON rg.role_id = c.id
     ORDER BY 1$$,
  ARRAY['project:read', 'project:write'],
  'a recursive CTE collects the grants of the role parent chain');
COMMIT;

-- rls_smoke: integrations
RESET ROLE;
INSERT INTO plugin_registrations (slug, enabled) VALUES ('github', true);
INSERT INTO integrations (id, organization_id, plugin_slug, name, slug,
                          used_as_login)
VALUES ('iLogin', NULL, 'github', 'GitHub', 'github', true),
       ('iA', 'orgA', 'github', 'GitHub A', 'github', false);
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT results_eq('SELECT id::text COLLATE "default" FROM integrations ORDER BY id',
                  ARRAY['iA', 'iLogin'],
                  'organization A sees its integration and the sign-in provider');
WITH changed AS (
  UPDATE integrations SET name = 'hijack' WHERE id = 'iLogin' RETURNING 1)
SELECT is(count(*)::int, 0,
          'organization A cannot update the sign-in provider')
  FROM changed;
SELECT throws_ok(
  $$INSERT INTO integrations (id, organization_id, plugin_slug, name, slug)
    VALUES ('iX', NULL, 'github', 'X', 'xx')$$,
  '42501', NULL,
  'imbi_app cannot insert an integration with no organization');
ROLLBACK;
BEGIN;
SELECT results_eq('SELECT id::text COLLATE "default" FROM integrations', ARRAY['iLogin'],
                  'with no setting only the sign-in provider is visible');
COMMIT;

-- rls_smoke: scoring
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT throws_ok(
  $$INSERT INTO scoring_policies (id, organization_id, name, slug, weight,
                                  parameters)
    VALUES ('sp1', 'orgA', 'S', 's', 10, '{"attribute_name": "x"}')$$,
  '23514', NULL,
  'an attribute policy needs a score map');
SELECT lives_ok(
  $$INSERT INTO scoring_policies (id, organization_id, name, slug, weight,
                                  parameters)
    VALUES ('sp1', 'orgA', 'S', 's', 10,
            '{"attribute_name": "x", "value_score_map": {"a": 1}}')$$,
  'an attribute policy with a score map can be inserted');
ROLLBACK;

-- rls_smoke: domains
RESET ROLE;
SELECT throws_ok(
  $$INSERT INTO teams (id, organization_id, name, slug)
    VALUES ('tBad', 'orgA', 'Bad', 'Bad Slug')$$,
  '23514', NULL, 'the slug domain rejects a space and upper case');
SELECT throws_ok(
  $$INSERT INTO teams (id, organization_id, name, slug)
    VALUES ('tBad2', 'orgA', 'Bad', 'trailing-')$$,
  '23514', NULL, 'the slug domain rejects a trailing hyphen');
SELECT throws_ok(
  $$UPDATE organizations SET attributes = '[]' WHERE id = 'orgA'$$,
  '23514', NULL, 'jsonb_object rejects an array');
SELECT throws_ok(
  $$UPDATE organizations SET tag_formats = '{}' WHERE id = 'orgA'$$,
  '23514', NULL, 'jsonb_array rejects an object');

-- rls_smoke: updated_at trigger
SELECT ok((SELECT updated_at IS NULL FROM teams WHERE id = 'tA'),
          'updated_at is NULL after an INSERT');
UPDATE teams SET name = 'Team A2' WHERE id = 'tA';
SELECT ok((SELECT updated_at IS NOT NULL FROM teams WHERE id = 'tA'),
          'updated_at is set after an UPDATE');

-- rls_smoke: advisories per organization
INSERT INTO components (id, purl_name, name, ecosystem)
VALUES ('c1', 'pkg:npm/express', 'express', 'npm');
INSERT INTO component_releases (id, component_id, version)
VALUES ('cr1', 'c1', '4.0.0');
INSERT INTO advisories (id, cve_id) VALUES ('adv1', 'CVE-2025-1234');
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
INSERT INTO component_advisories (organization_id, component_release_id,
                                  advisory_id, url, created_by)
VALUES ('orgA', 'cr1', 'adv1', 'https://a.example/cve', 'u1@example.com');
COMMIT;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgB', true);
INSERT INTO component_advisories (organization_id, component_release_id,
                                  advisory_id, url, created_by)
VALUES ('orgB', 'cr1', 'adv1', 'https://b.example/cve', 'u1@example.com');
COMMIT;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
WITH changed AS (
  UPDATE component_advisories SET url = 'https://a.example/v2'
   WHERE advisory_id = 'adv1' RETURNING 1)
SELECT is(count(*)::int, 1,
          'organization A updates only its own advisory link')
  FROM changed;
SELECT results_eq(
  $$SELECT organization_id::text COLLATE "default", url, updated_at IS NOT NULL
      FROM component_advisories$$,
  $$VALUES ('orgA', 'https://a.example/v2', true)$$,
  'organization A sees only its advisory link, updated');
COMMIT;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgB', true);
SELECT results_eq(
  'SELECT organization_id::text COLLATE "default", url FROM component_advisories',
  $$VALUES ('orgB', 'https://b.example/cve')$$,
  'organization B sees only its own advisory link');
COMMIT;
RESET ROLE;

-- review_smoke: setup. deploy sets the owners of the definer
-- functions, so the ALTER FUNCTION statements of the source file are
-- checks here.
SELECT is(pg_get_userbyid(p.proowner)::text, 'imbi_definer',
          format('%s is owned by imbi_definer', p.oid::regprocedure))
  FROM pg_proc AS p
 WHERE p.oid IN ('public.principal_permissions()'::regprocedure,
                 'public.principal_memberships()'::regprocedure,
                 'public.principal_teams()'::regprocedure,
                 'public.webhook_organization_id(text)'::regprocedure,
                 'public.upload_organization_id(text)'::regprocedure,
                 'public.integration_organization_id(text)'::regprocedure)
 ORDER BY p.proname;
INSERT INTO team_members (organization_id, team_id, user_id)
VALUES ('orgA', 'tA', 'u1');
INSERT INTO integrations (id, organization_id, plugin_slug, name, slug)
VALUES ('iA2', 'orgA', 'github', 'GitHub A2', 'github-two'),
       ('iB', 'orgB', 'github', 'GitHub B', 'github');
INSERT INTO webhooks (id, organization_id, name, slug, integration_id)
VALUES ('w1', 'orgA', 'Hook', 'hook', 'iA');
INSERT INTO uploads (id, organization_id, filename, content_type, file_size,
                     storage_key, uploaded_by)
VALUES ('up1', 'orgA', 'a.png', 'image/png', 10, 'uploads/up1/a.png',
        'u1@example.com');

-- review_smoke: A1 grants
SELECT ok(has_function_privilege('imbi_app', 'public.principal_permissions()',
                                 'EXECUTE'),
          'imbi_app can execute principal_permissions()');
SELECT ok(NOT has_function_privilege('imbi_admin',
                                     'public.principal_permissions()',
                                     'EXECUTE'),
          'imbi_admin cannot execute principal_permissions() (PUBLIC revoked)');

-- review_smoke: A1 principal only
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.principal_id', 'u1', true);
SELECT is(public.principal_permissions(), ARRAY['project:read'],
          'principal_permissions() gives the grants of the membership role');
SELECT is(public.principal_memberships(),
          '[{"role_slug": "admin", "organization_id": "orgA",
             "organization_name": "A", "organization_slug": "a"}]'::jsonb,
          'principal_memberships() gives the membership');
SELECT is(public.principal_teams(),
          '[{"team_name": "Team A2", "team_slug": "team",
             "organization_slug": "a"}]'::jsonb,
          'principal_teams() gives the team');
SELECT is((SELECT count(*) FROM roles)::int, 0,
          'roles stay hidden in the principal context');
COMMIT;

-- review_smoke: A1 resolvers with no context
BEGIN;
SELECT is(public.webhook_organization_id('w1'), 'orgA',
          'webhook_organization_id() finds the organization');
SELECT is(public.upload_organization_id('up1'), 'orgA',
          'upload_organization_id() finds the organization');
SELECT is(public.integration_organization_id('iLogin'), NULL,
          'integration_organization_id() is NULL for the sign-in provider');
SELECT is(public.integration_organization_id('iA'), 'orgA',
          'integration_organization_id() finds the organization');
COMMIT;

-- review_smoke: A2 conversations
RESET ROLE;
INSERT INTO principals (id, principal_type) VALUES ('u2', 'user');
INSERT INTO users (id, email, display_name)
VALUES ('u2', 'u2@example.com', 'U2');
INSERT INTO memberships (organization_id, principal_id, role_id)
VALUES ('orgA', 'u2', 'rA');
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT set_config('imbi.principal_id', 'u1', true);
INSERT INTO conversations (id, organization_id, user_id, model_name)
VALUES ('cv1', 'orgA', 'u1', 'claude');
INSERT INTO messages (id, organization_id, conversation_id, message_seq,
                      author_role, content)
VALUES ('m1', 'orgA', 'cv1', 0, 'user', 'hi');
COMMIT;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT set_config('imbi.principal_id', 'u1', true);
SELECT is((SELECT count(*) FROM conversations)::int, 1,
          'the owner sees the conversation');
COMMIT;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT set_config('imbi.principal_id', 'u2', true);
SELECT is((SELECT count(*) FROM conversations)::int, 0,
          'another principal does not see the conversation');
SELECT is((SELECT count(*) FROM messages)::int, 0,
          'another principal does not see the messages');
SELECT throws_ok(
  $$INSERT INTO messages (id, organization_id, conversation_id, message_seq,
                          author_role, content)
    VALUES ('m9', 'orgA', 'cv1', 9, 'user', 'x')$$,
  '42501', NULL,
  'another principal cannot add a message to the conversation');
ROLLBACK;

-- review_smoke: A3 imbi_admin and the sign-in providers
RESET ROLE;
SET ROLE imbi_admin;
SELECT lives_ok(
  $$INSERT INTO integrations (id, organization_id, plugin_slug, name, slug)
    VALUES ('iInst', NULL, 'github', 'GHE', 'ghe')$$,
  'imbi_admin can insert an instance integration');
WITH changed AS (
  UPDATE integrations SET name = 'GHE 2' WHERE id = 'iInst' RETURNING 1)
SELECT is(count(*)::int, 1, 'imbi_admin can update an instance integration')
  FROM changed;
SELECT is((SELECT count(*) FROM integrations
            WHERE organization_id IS NOT NULL)::int, 0,
          'imbi_admin sees no organization integrations');
RESET ROLE;

-- review_smoke: decision 4, login providers
SELECT throws_ok(
  $$UPDATE integrations SET used_as_login = true WHERE id = 'iA'$$,
  '23514', NULL,
  'an organization integration cannot be a login provider');
SELECT throws_ok(
  $$UPDATE integrations SET used_as_login = true WHERE id = 'iInst'$$,
  '23505', NULL,
  'the instance has only one login provider');

-- review_smoke: A4 identity_connections scope trigger
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT throws_ok(
  $$INSERT INTO identity_connections (id, integration_id, organization_id,
                                      user_id, subject)
    VALUES ('ic1', 'iA', NULL, 'u1', 's1')$$,
  '23503', NULL,
  'an organization integration needs its organization on the connection');
ROLLBACK;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT lives_ok(
  $$INSERT INTO identity_connections (id, integration_id, organization_id,
                                      user_id, subject)
    VALUES ('ic1', 'iA', 'orgA', 'u1', 's1')$$,
  'a connection to an integration of its organization can be inserted');
SELECT throws_ok(
  $$INSERT INTO identity_connections (id, integration_id, organization_id,
                                      user_id, subject)
    VALUES ('ic2', 'iB', 'orgA', 'u1', 's2')$$,
  '23503', NULL,
  'a connection cannot use an integration of another organization');
COMMIT;
BEGIN;
SELECT lives_ok(
  $$INSERT INTO identity_connections (id, integration_id, organization_id,
                                      user_id, subject)
    VALUES ('ic3', 'iLogin', NULL, 'u1', 's3')$$,
  'a connection to the sign-in provider needs no context');
COMMIT;

-- review_smoke: B1 Doctor results
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
INSERT INTO analysis_reports (id, organization_id, project_id, overall_status)
VALUES ('ar1', 'orgA', 'p1', 'pass');
SELECT lives_ok(
  $$INSERT INTO analysis_results (organization_id, report_id, slug, title,
                                  description, result_status, plugin_slug,
                                  integration_id)
    VALUES ('orgA', 'ar1', 'blueprint-compliance:all-pass', 'T', 'D', 'pass',
            'blueprint-compliance', 'built-in'),
           ('orgA', 'ar1', 'exists-in', 'T', 'D', 'pass', 'github', 'iA'),
           ('orgA', 'ar1', 'exists-in', 'T', 'D', 'pass', 'github', 'iA2')$$,
  'a colon slug, and one slug from two integrations, can be inserted');
ROLLBACK;

-- review_smoke: B2 message length
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT set_config('imbi.principal_id', 'u1', true);
SELECT lives_ok(
  $$INSERT INTO messages (id, organization_id, conversation_id, message_seq,
                          author_role, content)
    VALUES ('m2', 'orgA', 'cv1', 1, 'assistant', repeat('x', 40000))$$,
  'an assistant message can have 40000 characters');
SELECT throws_ok(
  $$INSERT INTO messages (id, organization_id, conversation_id, message_seq,
                          author_role, content)
    VALUES ('m3', 'orgA', 'cv1', 2, 'user', repeat('x', 40000))$$,
  '23514', NULL,
  'a user message cannot have 40000 characters');
ROLLBACK;

-- review_smoke: B3 scoring parameters
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT lives_ok(
  $$INSERT INTO scoring_policies (id, organization_id, name, slug, weight,
                                  parameters)
    VALUES ('sp2', 'orgA', 'S', 's2', 10,
            '{"attribute_name": "x", "value_score_map": {"a": 1},
              "range_score_map": null}')$$,
  'a NULL score map key is accepted');
SELECT throws_ok(
  $$INSERT INTO scoring_policies (id, organization_id, name, slug, weight,
                                  parameters)
    VALUES ('sp3', 'orgA', 'S', 's3', 10,
            '{"attribute_name": null, "value_score_map": {"a": 1}}')$$,
  '23514', NULL,
  'a NULL attribute_name is rejected');
ROLLBACK;

-- review_smoke: B4 uploads
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT lives_ok(
  $$INSERT INTO uploads (id, organization_id, filename, content_type,
                         file_size, storage_key, uploaded_by)
    VALUES ('up2', 'orgA', 'a.txt', 'text/plain', 62914560,
            'uploads/up2/a.txt', 'u1@example.com')$$,
  'a 60 MB text/plain upload is accepted');
ROLLBACK;

-- review_smoke: B5 webhook rule handler
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT lives_ok(
  $$INSERT INTO webhook_rules (organization_id, webhook_id, ordinal,
                               filter_expression, handler)
    VALUES ('orgA', 'w1', 0, 'true', 'github#sync')$$,
  'the handler github#sync is accepted');
SELECT throws_ok(
  $$INSERT INTO webhook_rules (organization_id, webhook_id, ordinal,
                               filter_expression, handler)
    VALUES ('orgA', 'w1', 1, 'true', 'GitHub#sync')$$,
  '23514', NULL,
  'the handler GitHub#sync is rejected');
ROLLBACK;

-- review_smoke: B9 webhook identity pin
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
WITH changed AS (
  UPDATE webhooks SET identity_integration_id = 'iLogin'
   WHERE id = 'w1' RETURNING 1)
SELECT is(count(*)::int, 1, 'a webhook can pin the sign-in provider')
  FROM changed;
SELECT throws_ok(
  $$UPDATE webhooks SET identity_integration_id = 'iB' WHERE id = 'w1'$$,
  '23503', NULL,
  'a webhook cannot pin an integration of another organization');
ROLLBACK;

-- review_smoke: C2 a no-op UPDATE does not set updated_at
RESET ROLE;
UPDATE teams SET name = name WHERE id = 'tB';
SELECT ok((SELECT updated_at IS NULL FROM teams WHERE id = 'tB'),
          'a no-op UPDATE keeps updated_at NULL');
UPDATE teams SET name = 'Team B2' WHERE id = 'tB';
SELECT ok((SELECT updated_at >= created_at FROM teams WHERE id = 'tB'),
          'a change sets updated_at');

-- review_smoke: D1. The source tested embeddings with no organization
-- for shared components. The second review (D2) removed them: every
-- embeddings row has an organization. test_behavior.sql T11 tests that
-- a superuser insert without one fails; this tests it for imbi_app.
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT throws_ok(
  $$INSERT INTO embeddings (organization_id, node_label, node_id, attribute,
                            model_name, chunk_text, embedding)
    VALUES (NULL, 'Component', 'c1', 'description', 'test', 'x', '[1,2,3]')$$,
  NULL, NULL,
  'imbi_app cannot insert an embedding with no organization');
ROLLBACK;

-- review_smoke: D2 the catalog
BEGIN;
SELECT throws_ok($$UPDATE components SET name = 'hijack' WHERE id = 'c1'$$,
                 '42501', NULL, 'imbi_app cannot update a catalog row');
SELECT throws_ok($$DELETE FROM advisories WHERE id = 'adv1'$$,
                 '42501', NULL, 'imbi_app cannot delete a catalog row');
WITH added AS (
  INSERT INTO components (id, purl_name, name, ecosystem)
  VALUES ('c2', 'pkg:npm/express', 'other name', 'npm')
  ON CONFLICT (purl_name) DO NOTHING RETURNING 1)
SELECT is(count(*)::int, 0, 'the first writer of a catalog row wins')
  FROM added;
ROLLBACK;
RESET ROLE;
SET ROLE imbi_maintenance;
BEGIN;
SELECT throws_ok($$DELETE FROM advisories WHERE id = 'adv1'$$,
                 '23001', NULL,
                 'an advisory that organizations use cannot be deleted');
ROLLBACK;
RESET ROLE;

-- review_smoke: D3 overrides
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SELECT lives_ok(
  $$INSERT INTO component_overrides (organization_id, component_id,
                                     description)
    VALUES ('orgA', 'c1', 'Our description')$$,
  'an organization can override a catalog value');
ROLLBACK;
RESET ROLE;

-- review_smoke: E3 delete a user
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
INSERT INTO documents (id, organization_id, user_id, title, content,
                       created_by)
VALUES ('d2', 'orgA', 'u2', 'Mine', 'text', 'u2@example.com');
COMMIT;
RESET ROLE;
DELETE FROM users WHERE id = 'u2';
SELECT results_eq(
  $$SELECT (SELECT count(*) FROM principals WHERE id = 'u2')::int,
           (SELECT count(*) FROM memberships WHERE principal_id = 'u2')::int,
           (SELECT count(*) FROM documents
             WHERE id = 'd2' AND user_id IS NULL)::int$$,
  $$VALUES (0, 0, 1)$$,
  'a user delete removes the principal and membership, the document stays');

-- review_smoke: E4 project delete removes embeddings
INSERT INTO documents (id, organization_id, project_id, title, content,
                       created_by)
VALUES ('d3', 'orgA', 'p1', 'Doc', 'text', 'u1@example.com');
INSERT INTO embeddings (organization_id, node_label, node_id, attribute,
                        model_name, chunk_text, embedding)
VALUES ('orgA', 'Project', 'p1', 'name', 'test', 'P', '[1,2,3]'),
       ('orgA', 'Document', 'd3', 'title', 'test', 'Doc', '[1,2,3]');
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
DELETE FROM analysis_reports WHERE project_id = 'p1';
DELETE FROM projects WHERE id = 'p1';
SELECT is((SELECT count(*) FROM embeddings
            WHERE node_id IN ('p1', 'd3'))::int, 0,
          'a project delete removes the embeddings of the project and its documents');
ROLLBACK;
RESET ROLE;

-- review_smoke: E1, E2, E5 RESTRICT deletes
INSERT INTO project_types (id, organization_id, name, slug)
VALUES ('pt1', 'orgA', 'API', 'api');
INSERT INTO document_templates (id, organization_id, name, slug)
VALUES ('dt1', 'orgA', 'Runbook', 'runbook');
INSERT INTO template_project_types (organization_id, document_template_id,
                                    project_type_id)
VALUES ('orgA', 'dt1', 'pt1');
SELECT throws_ok($$DELETE FROM teams WHERE id = 'tA'$$, '23001', NULL,
                 'a team with projects cannot be deleted');
SELECT throws_ok($$DELETE FROM project_types WHERE id = 'pt1'$$, '23001',
                 NULL,
                 'a project type that restricts a template cannot be deleted');
SELECT throws_ok($$DELETE FROM organizations WHERE id = 'orgB'$$, '23001',
                 NULL, 'an organization with rows cannot be deleted');

-- review_smoke: E6 release delete clears deployments.release_id
INSERT INTO environments (id, organization_id, name, slug)
VALUES ('e1', 'orgA', 'Production', 'production');
INSERT INTO releases (id, organization_id, project_id, tag, committish, title,
                      created_by)
VALUES ('rel1', 'orgA', 'p1', '1.0.0', 'abc1234', '1.0.0', 'u1@example.com');
INSERT INTO deployments (id, organization_id, project_id, environment_id,
                         release_id, deployment_status, transitioned_at)
VALUES ('dep1', 'orgA', 'p1', 'e1', 'rel1', 'success', now());
DELETE FROM releases WHERE id = 'rel1';
SELECT ok((SELECT release_id IS NULL FROM deployments WHERE id = 'dep1'),
          'a release delete sets deployments.release_id to NULL');

-- review_smoke: G3 the policy is an InitPlan and an index condition
CREATE FUNCTION pg_temp.plan_of(query text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
  line text;
  result text := '';
BEGIN
  FOR line IN EXECUTE 'EXPLAIN (COSTS OFF) ' || query LOOP
    result := result || line || E'\n';
  END LOOP;
  RETURN result;
END
$$;
SET ROLE imbi_app;
BEGIN;
SELECT set_config('imbi.organization_id', 'orgA', true);
SET LOCAL enable_seqscan = off;
SELECT matches(pg_temp.plan_of('SELECT id FROM deployments'),
               'Index Cond: \(organization_id = \(InitPlan 1\)',
               'the organization policy is an InitPlan index condition');
ROLLBACK;
RESET ROLE;
