-- Runbook step 5: prepare the AGE-era database for the first deploy.
--
--   psql -1 -v ON_ERROR_STOP=1 -f schemata/cutover/pre-deploy.sql
--
-- Run it as the operator (a superuser), after step 4 (no AGE-era
-- session remains). It:
--
-- 1. Stops unless the database is in the AGE-era state: public.embeddings
--    is the legacy table, and the schema legacy does not exist. After a
--    rollback (rollback.sql), the database is in that state again.
-- 2. Records in legacy.cutover_state what rollback.sql needs: the OID and
--    the row count of the legacy table, and the schema of the vector
--    extension. In production that schema is ag_catalog: the graph
--    initializer creates the extension with ag_catalog first in its
--    search_path. The deploy moves the extension to public, and
--    rollback.sql moves it back.
-- 3. Moves public.embedding_distance(agtype, ...) into the schema legacy.
--    Nothing calls it, and deploy would propose to drop it. A move, not
--    a drop, so rollback.sql can put it back as it was. The default
--    search_path does not find agtype, so the types are qualified.
-- 4. Moves public.embeddings into the schema legacy. Its indexes, owner,
--    and grants move with it, so the index names do not collide with the
--    indexes of the new table. ALTER TABLE ... RENAME does not work: the
--    indexes keep their names in public, and the new HNSW index fails.
--
-- The deploy (step 6) runs with -N legacy, so it does not see the
-- legacy objects.
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
    IF to_regnamespace('legacy') IS NOT NULL THEN
        RAISE EXCEPTION 'pre-deploy: schema legacy exists'
              USING HINT = 'Run schemata/cutover/rollback.sql first.';
    END IF;
    IF to_regclass('public.embeddings') IS NULL THEN
        RAISE EXCEPTION 'pre-deploy: public.embeddings does not exist'
              USING HINT = 'This is not an AGE-era database.';
    END IF;
    IF EXISTS (SELECT 1
                 FROM pg_catalog.pg_attribute
                WHERE attrelid = 'public.embeddings'::regclass
                  AND attname = 'organization_id'
                  AND NOT attisdropped) THEN
        RAISE EXCEPTION 'pre-deploy: public.embeddings is the new table'
              USING HINT = 'Run schemata/cutover/rollback.sql first.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_extension
                    WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pre-deploy: extension vector is not installed';
    END IF;
END
$$;

CREATE SCHEMA legacy;

CREATE TABLE legacy.cutover_state AS
     SELECT 'public.embeddings'::regclass::oid AS embeddings_oid,
            (SELECT count(*) FROM public.embeddings) AS embeddings_rows,
            (SELECT n.nspname::text
               FROM pg_catalog.pg_extension AS e
               JOIN pg_catalog.pg_namespace AS n
                 ON n.oid = e.extnamespace
              WHERE e.extname = 'vector') AS vector_schema,
            statement_timestamp() AS recorded_at;

DO $$
BEGIN
    IF to_regprocedure('public.embedding_distance(ag_catalog.agtype, '
                       'ag_catalog.agtype, ag_catalog.agtype, '
                       'ag_catalog.agtype)') IS NOT NULL THEN
        ALTER FUNCTION public.embedding_distance(
            ag_catalog.agtype, ag_catalog.agtype, ag_catalog.agtype,
            ag_catalog.agtype) SET SCHEMA legacy;
    END IF;
END
$$;

ALTER TABLE public.embeddings SET SCHEMA legacy;
