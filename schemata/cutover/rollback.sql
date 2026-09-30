-- Runbook rollback, step 2: put the legacy objects back.
--
--   psql -1 -v ON_ERROR_STOP=1 -f schemata/cutover/rollback.sql
--
-- Run it as the operator (a superuser), after every app is stopped. Use
-- it only before runbook step 13. It can run after a failure at any
-- step from step 5 on, and it can run again: a second run changes
-- nothing.
--
-- What it does, where the object exists:
--
-- 1. Stops unless legacy.embeddings is the table that pre-deploy.sql
--    moved (the OID in legacy.cutover_state).
-- 2. Drops the new public.embeddings (a different OID, with
--    organization_id), and only when legacy.embeddings exists. It never
--    drops the legacy table. The drop is RESTRICT: it fails if another
--    object depends on the new table.
-- 3. Moves legacy.embeddings back to public. The table keeps its rows,
--    indexes, owner, and grants.
-- 4. Moves legacy.embedding_distance(agtype, ...) back to public.
-- 5. Moves the vector extension back to the schema that pre-deploy.sql
--    recorded.
-- 6. Drops legacy.cutover_state and the schema legacy. The drop of the
--    schema is RESTRICT: it fails if anything else is in it.
--
-- The relational tables stay. The AGE-era code does not read them, and
-- a new attempt starts again at runbook step 3.
SET LOCAL lock_timeout = '10s';

DO $$
DECLARE
    v_state record;
    v_have_state boolean := false;
    v_rows bigint;
    v_vector_schema text;
BEGIN
    IF to_regclass('legacy.cutover_state') IS NOT NULL THEN
        SELECT * INTO v_state FROM legacy.cutover_state;
        v_have_state := FOUND;
    END IF;

    IF to_regclass('legacy.embeddings') IS NOT NULL THEN
        IF v_have_state
           AND 'legacy.embeddings'::regclass::oid <> v_state.embeddings_oid
        THEN
            RAISE EXCEPTION
                  'rollback: legacy.embeddings is not the moved table'
                  USING HINT = 'Stop. A person must look at it.';
        END IF;
        IF to_regclass('public.embeddings') IS NOT NULL THEN
            IF NOT EXISTS (SELECT 1
                             FROM pg_catalog.pg_attribute
                            WHERE attrelid = 'public.embeddings'::regclass
                              AND attname = 'organization_id'
                              AND NOT attisdropped) THEN
                RAISE EXCEPTION
                      'rollback: legacy.embeddings and a legacy-shaped '
                      'public.embeddings both exist'
                      USING HINT = 'Stop. A person must look at both.';
            END IF;
            RAISE NOTICE 'rollback: dropping the new public.embeddings';
            DROP TABLE public.embeddings;
        END IF;
        RAISE NOTICE 'rollback: moving legacy.embeddings to public';
        ALTER TABLE legacy.embeddings SET SCHEMA public;
        IF v_have_state THEN
            SELECT count(*) INTO v_rows FROM public.embeddings;
            IF v_rows <> v_state.embeddings_rows THEN
                RAISE WARNING 'rollback: public.embeddings has % rows, '
                              'pre-deploy recorded %',
                              v_rows, v_state.embeddings_rows;
            END IF;
        END IF;
    ELSIF to_regclass('public.embeddings') IS NULL THEN
        RAISE EXCEPTION 'rollback: no embeddings table exists'
              USING HINT = 'Stop. The legacy table is missing.';
    ELSIF EXISTS (SELECT 1
                    FROM pg_catalog.pg_attribute
                   WHERE attrelid = 'public.embeddings'::regclass
                     AND attname = 'organization_id'
                     AND NOT attisdropped) THEN
        RAISE EXCEPTION
              'rollback: only the new public.embeddings exists'
              USING HINT = 'Stop. The legacy table is missing.';
    END IF;

    IF to_regprocedure('legacy.embedding_distance(ag_catalog.agtype, '
                       'ag_catalog.agtype, ag_catalog.agtype, '
                       'ag_catalog.agtype)') IS NOT NULL THEN
        RAISE NOTICE 'rollback: moving embedding_distance to public';
        ALTER FUNCTION legacy.embedding_distance(
            ag_catalog.agtype, ag_catalog.agtype, ag_catalog.agtype,
            ag_catalog.agtype) SET SCHEMA public;
    END IF;

    IF v_have_state THEN
        SELECT extnamespace::regnamespace::text INTO v_vector_schema
          FROM pg_catalog.pg_extension
         WHERE extname = 'vector';
        IF v_state.vector_schema IS NOT NULL
           AND v_state.vector_schema IS DISTINCT FROM v_vector_schema THEN
            RAISE NOTICE 'rollback: moving extension vector to %',
                         v_state.vector_schema;
            EXECUTE format('ALTER EXTENSION vector SET SCHEMA %I',
                           v_state.vector_schema);
        END IF;
        DROP TABLE legacy.cutover_state;
    END IF;

    IF to_regnamespace('legacy') IS NOT NULL THEN
        RAISE NOTICE 'rollback: dropping schema legacy';
        DROP SCHEMA legacy;
    END IF;
END
$$;
