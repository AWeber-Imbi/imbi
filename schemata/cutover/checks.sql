-- Runbook step 6: the structure checks of the cutover.
--
-- Run it in the same transaction as the deploy plan and the owners:
--
--   psql -1 -v ON_ERROR_STOP=1 -f cutover.sql \
--        -f schemata/scripts/set-owners.sql -f schemata/cutover/checks.sql
--
-- Each check raises an error when the database is not as expected, so
-- the transaction rolls back and the deploy has no effect. The expected
-- values are from schemata/ and schemata/registry.toml. When the
-- schema changes, change this file too: root:cutover-check runs it
-- against a new deploy and fails when a value is out of date.

-- The tables of the project, and their scope from registry.toml.
CREATE TEMPORARY TABLE cutover_expected_tables (
    name text PRIMARY KEY,
    scope text NOT NULL
) ON COMMIT DROP;

INSERT INTO cutover_expected_tables (name, scope)
     VALUES
        ('advisories', 'catalog'),
        ('ai_model_teams', 'organization'),
        ('ai_models', 'organization'),
        ('ai_providers', 'organization'),
        ('analysis_reports', 'organization'),
        ('analysis_results', 'organization'),
        ('api_keys', 'instance'),
        ('blockers', 'organization'),
        ('blueprints', 'organization'),
        ('client_credentials', 'instance'),
        ('comment_threads', 'organization'),
        ('comments', 'organization'),
        ('component_advisories', 'organization'),
        ('component_governance', 'organization'),
        ('component_identifiers', 'catalog'),
        ('component_notes', 'organization'),
        ('component_overrides', 'organization'),
        ('component_release_governance', 'organization'),
        ('component_release_overrides', 'organization'),
        ('component_releases', 'catalog'),
        ('components', 'catalog'),
        ('conversations', 'organization'),
        ('deployments', 'organization'),
        ('document_likes', 'organization'),
        ('document_tags', 'organization'),
        ('document_templates', 'organization'),
        ('documents', 'organization'),
        ('embeddings', 'organization'),
        ('environments', 'organization'),
        ('identity_connections', 'instance'),
        ('integrations', 'organization'),
        ('issued_tokens', 'instance'),
        ('link_definitions', 'organization'),
        ('local_auth_settings', 'instance'),
        ('mcp_servers', 'organization'),
        ('memberships', 'organization'),
        ('messages', 'organization'),
        ('oauth_clients', 'instance'),
        ('organizations', 'tenancy'),
        ('password_reset_tokens', 'instance'),
        ('permissions', 'instance'),
        ('plugin_edges', 'organization'),
        ('plugin_entities', 'organization'),
        ('plugin_entity_keys', 'organization'),
        ('plugin_registrations', 'instance'),
        ('principals', 'instance'),
        ('project_capabilities', 'organization'),
        ('project_dependencies', 'organization'),
        ('project_environments', 'organization'),
        ('project_integrations', 'organization'),
        ('project_promotions', 'organization'),
        ('project_syncs', 'organization'),
        ('project_type_assignments', 'organization'),
        ('project_type_capabilities', 'organization'),
        ('project_types', 'organization'),
        ('projects', 'organization'),
        ('releases', 'organization'),
        ('resource_acls', 'organization'),
        ('role_grants', 'organization'),
        ('roles', 'organization'),
        ('scoring_policies', 'organization'),
        ('scoring_policy_targets', 'organization'),
        ('service_accounts', 'instance'),
        ('tags', 'organization'),
        ('team_members', 'organization'),
        ('teams', 'organization'),
        ('template_project_types', 'organization'),
        ('template_tags', 'organization'),
        ('tenants', 'tenancy'),
        ('totp_secrets', 'instance'),
        ('uploads', 'organization'),
        ('users', 'instance'),
        ('webhook_rules', 'organization'),
        ('webhooks', 'organization');

-- The table privileges of each role on the tables in public, as
-- (grantee, privilege, number of tables). imbi_owner is the owner and
-- is not in the list.
CREATE TEMPORARY TABLE cutover_expected_grants (
    grantee text NOT NULL,
    privilege text NOT NULL,
    tables integer NOT NULL,
    PRIMARY KEY (grantee, privilege)
) ON COMMIT DROP;

INSERT INTO cutover_expected_grants (grantee, privilege, tables)
     VALUES
        ('imbi_admin', 'DELETE', 1),
        ('imbi_admin', 'INSERT', 1),
        ('imbi_admin', 'SELECT', 2),
        ('imbi_admin', 'UPDATE', 1),
        ('imbi_app', 'DELETE', 69),
        ('imbi_app', 'INSERT', 73),
        ('imbi_app', 'SELECT', 74),
        ('imbi_app', 'UPDATE', 69),
        ('imbi_definer', 'SELECT', 9),
        ('imbi_maintenance', 'DELETE', 74),
        ('imbi_maintenance', 'INSERT', 74),
        ('imbi_maintenance', 'SELECT', 74),
        ('imbi_maintenance', 'TRUNCATE', 74),
        ('imbi_maintenance', 'UPDATE', 74),
        ('imbi_trigger', 'DELETE', 2),
        ('imbi_trigger', 'SELECT', 2);

-- 1. The tables in public are the tables of the project.
DO $$
DECLARE
    v_missing text;
    v_extra text;
BEGIN
    SELECT string_agg(e.name, ', ' ORDER BY e.name)
      INTO v_missing
      FROM cutover_expected_tables AS e
     WHERE to_regclass(format('public.%I', e.name)) IS NULL;
    SELECT string_agg(c.relname, ', ' ORDER BY c.relname)
      INTO v_extra
      FROM pg_catalog.pg_class AS c
     WHERE c.relnamespace = 'public'::regnamespace
       AND c.relkind IN ('r', 'p')
       AND c.relname NOT IN (SELECT name FROM cutover_expected_tables);
    IF v_missing IS NOT NULL OR v_extra IS NOT NULL THEN
        RAISE EXCEPTION 'cutover check: tables in public are wrong'
              USING DETAIL = format('missing: %s; not expected: %s',
                                    coalesce(v_missing, 'none'),
                                    coalesce(v_extra, 'none'));
    END IF;
END
$$;

-- 2. The new embeddings table is in public, and the legacy table is in
--    legacy. The vector extension is in public, where the project puts
--    it.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1
                     FROM pg_catalog.pg_attribute
                    WHERE attrelid = 'public.embeddings'::regclass
                      AND attname = 'organization_id'
                      AND NOT attisdropped) THEN
        RAISE EXCEPTION
              'cutover check: public.embeddings is not the new table';
    END IF;
    IF to_regclass('legacy.embeddings') IS NULL THEN
        RAISE EXCEPTION 'cutover check: legacy.embeddings is missing';
    END IF;
    IF (SELECT extnamespace::regnamespace::text
          FROM pg_catalog.pg_extension
         WHERE extname = 'vector') IS DISTINCT FROM 'public' THEN
        RAISE EXCEPTION 'cutover check: extension vector is not in public';
    END IF;
END
$$;

-- 3. Row-level security: ENABLE and FORCE on each organization table
--    and on organizations, and no row-level security on the others.
DO $$
DECLARE
    v_wrong text;
BEGIN
    SELECT string_agg(format('%s (enabled %s, forced %s)', c.relname,
                             c.relrowsecurity, c.relforcerowsecurity),
                      ', ' ORDER BY c.relname)
      INTO v_wrong
      FROM cutover_expected_tables AS e
      JOIN pg_catalog.pg_class AS c
        ON c.oid = to_regclass(format('public.%I', e.name))
     WHERE (c.relrowsecurity AND c.relforcerowsecurity)
           IS DISTINCT FROM (e.scope = 'organization'
                             OR e.name = 'organizations')
        OR c.relrowsecurity IS DISTINCT FROM c.relforcerowsecurity;
    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION 'cutover check: row-level security is wrong'
              USING DETAIL = v_wrong;
    END IF;
    IF (SELECT count(*) FROM pg_catalog.pg_policies
         WHERE schemaname = 'public') <> 62 THEN
        RAISE EXCEPTION 'cutover check: expected 62 policies in public';
    END IF;
END
$$;

-- 4. Owners. The tables, the domains, and the functions that are not
--    SECURITY DEFINER belong to imbi_owner. delete_embeddings() and
--    delete_plugin_edges() belong to imbi_trigger, the other SECURITY
--    DEFINER functions to imbi_definer. Objects of an extension (vector
--    is in public) are not checked.
DO $$
DECLARE
    v_wrong text;
BEGIN
    SELECT string_agg(format('%s %s: %s', kind, name, owner),
                      ', ' ORDER BY kind, name)
      INTO v_wrong
      FROM (SELECT 'table' AS kind, c.relname::text AS name,
                   pg_catalog.pg_get_userbyid(c.relowner)::text AS owner,
                   'imbi_owner' AS expected
              FROM pg_catalog.pg_class AS c
             WHERE c.relnamespace = 'public'::regnamespace
               AND c.relkind IN ('r', 'p')
            UNION ALL
            SELECT 'domain', t.typname::text,
                   pg_catalog.pg_get_userbyid(t.typowner)::text,
                   'imbi_owner'
              FROM pg_catalog.pg_type AS t
             WHERE t.typnamespace = 'public'::regnamespace
               AND t.typtype = 'd'
            UNION ALL
            SELECT 'function', p.oid::regprocedure::text,
                   pg_catalog.pg_get_userbyid(p.proowner)::text,
                   CASE
                       WHEN p.proname IN ('delete_embeddings',
                                          'delete_plugin_edges')
                       THEN 'imbi_trigger'
                       WHEN p.prosecdef THEN 'imbi_definer'
                       ELSE 'imbi_owner'
                   END
              FROM pg_catalog.pg_proc AS p
             WHERE p.pronamespace = 'public'::regnamespace
               AND NOT EXISTS (
                       SELECT 1
                         FROM pg_catalog.pg_depend AS d
                        WHERE d.classid = 'pg_catalog.pg_proc'::regclass
                          AND d.objid = p.oid
                          AND d.deptype = 'e')) AS o
     WHERE owner <> expected;
    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION 'cutover check: owners are wrong'
              USING DETAIL = v_wrong;
    END IF;
    IF (SELECT count(*)
          FROM pg_catalog.pg_proc AS p
         WHERE p.pronamespace = 'public'::regnamespace
           AND p.prosecdef
           AND pg_catalog.pg_get_userbyid(p.proowner) = 'imbi_definer')
       <> 6 THEN
        RAISE EXCEPTION
              'cutover check: expected 6 functions owned by imbi_definer';
    END IF;
END
$$;

-- 5. Table grants. Each role has exactly the privileges of the project,
--    and no other role (PUBLIC included) has a privilege on a table in
--    public. This finds grants that default privileges of the AGE-era
--    database add to the new tables.
DO $$
DECLARE
    v_wrong text;
BEGIN
    WITH actual AS (
        SELECT CASE a.grantee WHEN 0 THEN 'PUBLIC'
                    ELSE pg_catalog.pg_get_userbyid(a.grantee)::text
               END AS grantee,
               a.privilege_type AS privilege,
               count(*)::integer AS tables
          FROM pg_catalog.pg_class AS c,
               LATERAL aclexplode(c.relacl) AS a
         WHERE c.relnamespace = 'public'::regnamespace
           AND c.relkind IN ('r', 'p')
           AND a.grantee <> c.relowner
         GROUP BY 1, 2)
    SELECT string_agg(format('%s %s: %s tables, expected %s',
                             coalesce(a.grantee, e.grantee),
                             coalesce(a.privilege, e.privilege),
                             coalesce(a.tables, 0),
                             coalesce(e.tables, 0)),
                      ', ')
      INTO v_wrong
      FROM actual AS a
      FULL JOIN cutover_expected_grants AS e
        ON e.grantee = a.grantee AND e.privilege = a.privilege
     WHERE a.tables IS DISTINCT FROM e.tables;
    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION 'cutover check: table grants are wrong'
              USING DETAIL = v_wrong;
    END IF;
    -- The catalog is insert-only and tenants is read-only for imbi_app.
    IF EXISTS (SELECT 1
                 FROM cutover_expected_tables AS e
                WHERE (e.scope = 'catalog' OR e.name = 'tenants')
                  AND (has_table_privilege('imbi_app',
                                           format('public.%I', e.name),
                                           'UPDATE, DELETE, TRUNCATE')
                       OR (e.name = 'tenants'
                           AND has_table_privilege('imbi_app',
                                                   'public.tenants',
                                                   'INSERT')))) THEN
        RAISE EXCEPTION
              'cutover check: imbi_app can change the catalog or tenants';
    END IF;
    -- imbi_admin cannot touch embeddings; imbi_trigger reaches only
    -- embeddings and plugin_edges.
    IF has_table_privilege('imbi_admin', 'public.embeddings',
                           'SELECT, INSERT, UPDATE, DELETE') THEN
        RAISE EXCEPTION
              'cutover check: imbi_admin has a grant on embeddings';
    END IF;
    IF EXISTS (SELECT 1
                 FROM cutover_expected_tables AS e
                WHERE e.name NOT IN ('embeddings', 'plugin_edges')
                  AND has_table_privilege('imbi_trigger',
                                          format('public.%I', e.name),
                                          'SELECT, INSERT, UPDATE, DELETE'))
    THEN
        RAISE EXCEPTION 'cutover check: imbi_trigger has too many grants';
    END IF;
    -- No application role can read the legacy schema.
    IF has_schema_privilege('imbi_app', 'legacy', 'USAGE')
       OR has_schema_privilege('imbi_admin', 'legacy', 'USAGE') THEN
        RAISE EXCEPTION 'cutover check: an app role can use schema legacy';
    END IF;
END
$$;

-- 6. Function grants. PUBLIC cannot execute a SECURITY DEFINER
--    function. imbi_app can execute the six lookup functions, and no
--    login role can execute the two delete trigger functions directly.
DO $$
DECLARE
    v_wrong text;
BEGIN
    SELECT string_agg(p.oid::regprocedure::text, ', ')
      INTO v_wrong
      FROM pg_catalog.pg_proc AS p
     WHERE p.pronamespace = 'public'::regnamespace
       AND p.prosecdef
       AND (p.proacl IS NULL
            OR EXISTS (SELECT 1 FROM aclexplode(p.proacl) AS a
                        WHERE a.grantee = 0));
    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION
              'cutover check: PUBLIC can execute SECURITY DEFINER functions'
              USING DETAIL = v_wrong;
    END IF;
    SELECT string_agg(p.oid::regprocedure::text, ', ')
      INTO v_wrong
      FROM pg_catalog.pg_proc AS p
     WHERE p.pronamespace = 'public'::regnamespace
       AND p.prosecdef
       AND (has_function_privilege('imbi_app', p.oid, 'EXECUTE')
            IS DISTINCT FROM (pg_catalog.pg_get_userbyid(p.proowner)
                              = 'imbi_definer')
            OR has_function_privilege('imbi_admin', p.oid, 'EXECUTE')
               AND p.proname IN ('delete_embeddings',
                                 'delete_plugin_edges')
            OR has_function_privilege('imbi_maintenance', p.oid,
                                      'EXECUTE')
               AND p.proname IN ('delete_embeddings',
                                 'delete_plugin_edges'));
    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION 'cutover check: function grants are wrong'
              USING DETAIL = v_wrong;
    END IF;
END
$$;

-- 7. Role attributes. The owner roles cannot log in, imbi_app and
--    imbi_admin do not bypass row-level security, and no login role is
--    a member of imbi_owner, imbi_definer, or imbi_trigger.
DO $$
DECLARE
    v_wrong text;
BEGIN
    SELECT string_agg(rolname, ', ' ORDER BY rolname)
      INTO v_wrong
      FROM pg_catalog.pg_roles
     WHERE (rolname IN ('imbi_owner', 'imbi_definer', 'imbi_trigger')
            AND rolcanlogin)
        OR (rolname IN ('imbi_app', 'imbi_admin')
            AND (rolbypassrls OR rolsuper OR NOT rolcanlogin))
        OR (rolname IN ('imbi_definer', 'imbi_trigger',
                        'imbi_maintenance')
            AND NOT rolbypassrls);
    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION 'cutover check: role attributes are wrong'
              USING DETAIL = v_wrong;
    END IF;
    SELECT string_agg(format('%s in %s', m.rolname, g.rolname), ', ')
      INTO v_wrong
      FROM pg_catalog.pg_auth_members AS am
      JOIN pg_catalog.pg_roles AS g ON g.oid = am.roleid
      JOIN pg_catalog.pg_roles AS m ON m.oid = am.member
     WHERE g.rolname IN ('imbi_owner', 'imbi_definer', 'imbi_trigger')
       AND m.rolcanlogin
       AND NOT m.rolsuper;
    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION 'cutover check: a login role is in an owner role'
              USING DETAIL = v_wrong;
    END IF;
END
$$;

-- 8. The counts that schemata/README.md "Table map" gives.
DO $$
BEGIN
    IF (SELECT count(*)
          FROM pg_catalog.pg_trigger AS t
          JOIN pg_catalog.pg_class AS c ON c.oid = t.tgrelid
         WHERE c.relnamespace = 'public'::regnamespace
           AND NOT t.tgisinternal) <> 67 THEN
        RAISE EXCEPTION 'cutover check: expected 67 triggers in public';
    END IF;
    IF (SELECT count(*)
          FROM pg_catalog.pg_constraint
         WHERE connamespace = 'public'::regnamespace
           AND contype = 'f') <> 139 THEN
        RAISE EXCEPTION
              'cutover check: expected 139 foreign keys in public';
    END IF;
END
$$;

-- 9. Every index is valid and ready, every constraint is validated, and
--    each SECURITY DEFINER function has search_path = pg_catalog,
--    pg_temp, so a temporary object of the caller cannot shadow a name
--    in its body (schemata/README.md "Row-level security").
DO $$
DECLARE
    v_wrong text;
BEGIN
    SELECT string_agg(i.indexrelid::regclass::text, ', ')
      INTO v_wrong
      FROM pg_catalog.pg_index AS i
      JOIN pg_catalog.pg_class AS c ON c.oid = i.indrelid
     WHERE c.relnamespace = 'public'::regnamespace
       AND NOT (i.indisvalid AND i.indisready);
    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION 'cutover check: indexes are not valid'
              USING DETAIL = v_wrong;
    END IF;
    SELECT string_agg(conname, ', ')
      INTO v_wrong
      FROM pg_catalog.pg_constraint
     WHERE connamespace = 'public'::regnamespace
       AND NOT convalidated;
    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION 'cutover check: constraints are not validated'
              USING DETAIL = v_wrong;
    END IF;
    SELECT string_agg(p.oid::regprocedure::text, ', ')
      INTO v_wrong
      FROM pg_catalog.pg_proc AS p
     WHERE p.pronamespace = 'public'::regnamespace
       AND p.prosecdef
       AND p.proconfig IS DISTINCT FROM
           ARRAY['search_path=pg_catalog, pg_temp'];
    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION
              'cutover check: SECURITY DEFINER search_path is wrong'
              USING DETAIL = v_wrong;
    END IF;
END
$$;
