-- Runbook step 9: probe row-level security on the loaded data, as
-- imbi_app.
--
--   psql -v ON_ERROR_STOP=1 -v org_id=<id of an organization> \
--        -f schemata/cutover/rls-probe.sql
--
-- Run it as the operator (a superuser), after the ETL and before step
-- 11. Do not use -1: the script starts its own transaction and rolls it
-- back, so it changes nothing. Production has one organization, so the
-- API cannot request a row of another organization. This script tests
-- the policies directly:
--
-- 1. For each table with forced row-level security and an
--    organization_id column, imbi_app with the organization setting sees
--    exactly the rows of that organization.
-- 2. With the setting of an organization that does not exist, imbi_app
--    sees no rows.
-- 3. With no setting, imbi_app sees no rows, except the integrations
--    that have no organization (the instance sign-in provider).
-- 4. imbi_app cannot insert a row for another organization.
BEGIN;

SELECT set_config('cutover.probe_org', :'org_id', true) AS probe_org \gset

DO $$
DECLARE
    v_org text := current_setting('cutover.probe_org');
    v_table text;
    v_expected bigint;
    v_actual bigint;
    v_total bigint := 0;
    v_tables integer := 0;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.organizations WHERE id = v_org)
    THEN
        RAISE EXCEPTION 'rls probe: organization % does not exist', v_org;
    END IF;
    FOR v_table IN
        SELECT c.relname
          FROM pg_catalog.pg_class AS c
         WHERE c.relnamespace = 'public'::regnamespace
           AND c.relkind = 'r'
           AND c.relforcerowsecurity
           AND EXISTS (SELECT 1 FROM pg_catalog.pg_attribute AS a
                        WHERE a.attrelid = c.oid
                          AND a.attname = 'organization_id'
                          AND NOT a.attisdropped)
         ORDER BY c.relname
    LOOP
        v_tables := v_tables + 1;
        -- The operator is a superuser, so row-level security does not
        -- apply to this count.
        EXECUTE format('SELECT count(*) FROM public.%I
                         WHERE organization_id = $1', v_table)
           INTO v_expected USING v_org;
        v_total := v_total + v_expected;

        EXECUTE 'SET LOCAL ROLE imbi_app';

        PERFORM set_config('imbi.organization_id', v_org, true);
        EXECUTE format('SELECT count(*) FROM public.%I', v_table)
           INTO v_actual;
        IF v_actual <> v_expected THEN
            RAISE EXCEPTION 'rls probe: % shows % rows of %, expected %',
                            v_table, v_actual, v_org, v_expected;
        END IF;

        PERFORM set_config('imbi.organization_id',
                           'cutover-probe-no-such-organization', true);
        EXECUTE format('SELECT count(*) FROM public.%I', v_table)
           INTO v_actual;
        IF v_actual <> 0 THEN
            RAISE EXCEPTION
                  'rls probe: % shows % rows to an unknown organization',
                  v_table, v_actual;
        END IF;

        PERFORM set_config('imbi.organization_id', '', true);
        EXECUTE format('SELECT count(*) FROM public.%I
                         WHERE organization_id IS NOT NULL', v_table)
           INTO v_actual;
        IF v_actual <> 0 THEN
            RAISE EXCEPTION
                  'rls probe: % shows % rows with no organization setting',
                  v_table, v_actual;
        END IF;

        EXECUTE 'RESET ROLE';
    END LOOP;

    EXECUTE 'SET LOCAL ROLE imbi_app';
    PERFORM set_config('imbi.organization_id', v_org, true);
    BEGIN
        INSERT INTO public.tags (id, organization_id, name, slug)
             VALUES ('cutover-probe', 'cutover-probe-no-such-organization',
                     'Cutover probe', 'cutover-probe');
        RAISE EXCEPTION 'rls probe: imbi_app inserted a row for another '
                        'organization';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;
    END;
    EXECUTE 'RESET ROLE';

    IF v_total = 0 THEN
        RAISE EXCEPTION 'rls probe: organization % has no rows', v_org;
    END IF;
    RAISE NOTICE 'rls probe: % tables, % rows of %, isolation holds',
                 v_tables, v_total, v_org;
END
$$;

ROLLBACK;
