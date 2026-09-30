-- Check the owners of README "Roles" after a deploy.
--
-- pglifecycle deploy sets the owner that each YAML file names (pglifecycle
-- commit 47c58cc, in the pinned build), so this script does not change
-- owners. It stops with an error when an object in public has an owner
-- that is not correct:
--
--   delete_embeddings(), delete_plugin_edges()     imbi_trigger
--   the other SECURITY DEFINER functions           imbi_definer
--   every other function, table, sequence, view,   imbi_owner
--   and domain
--
-- Functions of extensions are not checked. The script makes no changes,
-- so you can run it any number of times, also inside the cutover
-- transaction (psql -1).
DO $$
DECLARE
  wrong text;
BEGIN
  WITH objects AS (
       SELECT format('%s %s', CASE c.relkind
                                WHEN 'S' THEN 'sequence'
                                WHEN 'v' THEN 'view'
                                WHEN 'm' THEN 'materialized view'
                                ELSE 'table'
                              END, c.oid::regclass) AS name,
              pg_get_userbyid(c.relowner) AS owner,
              'imbi_owner' AS expected
         FROM pg_class AS c
        WHERE c.relnamespace = 'public'::regnamespace
          AND c.relkind IN ('r', 'p', 'S', 'v', 'm')
          AND NOT EXISTS (SELECT 1 FROM pg_depend AS d
                           WHERE d.classid = 'pg_class'::regclass
                             AND d.objid = c.oid
                             AND d.deptype IN ('e', 'a', 'i'))
        UNION ALL
       SELECT format('function %s', p.oid::regprocedure),
              pg_get_userbyid(p.proowner),
              CASE
                WHEN p.proname IN ('delete_embeddings',
                                   'delete_plugin_edges')
                  THEN 'imbi_trigger'
                WHEN p.prosecdef THEN 'imbi_definer'
                ELSE 'imbi_owner'
              END
         FROM pg_proc AS p
        WHERE p.pronamespace = 'public'::regnamespace
          AND NOT EXISTS (SELECT 1 FROM pg_depend AS d
                           WHERE d.classid = 'pg_proc'::regclass
                             AND d.objid = p.oid
                             AND d.deptype = 'e')
        UNION ALL
       SELECT format('domain %s', t.oid::regtype),
              pg_get_userbyid(t.typowner),
              'imbi_owner'
         FROM pg_type AS t
        WHERE t.typnamespace = 'public'::regnamespace
          AND t.typtype = 'd')
  SELECT string_agg(format('%s is owned by %s, not %s',
                           name, owner, expected), E'\n' ORDER BY name)
    INTO wrong
    FROM objects
   WHERE owner <> expected;
  IF wrong IS NOT NULL THEN
    RAISE EXCEPTION 'wrong owners in schema public'
          USING DETAIL = wrong,
                HINT = 'Set the owner in the YAML file of the object and '
                       'deploy again.';
  END IF;
END
$$;
