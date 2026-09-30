-- Create the six roles of README "Roles". deploy does not create roles,
-- so run this once for each cluster, before the first deploy.
--
-- The three login passwords come from psql variables:
--
--   psql -v app_password=... \
--        -v admin_password=... \
--        -v maintenance_password=... \
--        -f schemata/scripts/create-roles.sql
--
-- The script creates only the roles that do not exist, so you can run it
-- again. It does not change a role that exists, but it stops with an
-- error when an existing role has LOGIN, BYPASSRLS or SUPERUSER set
-- differently from README "Roles". It also stops, before it creates a
-- role, when a password variable is not set.
\set ON_ERROR_STOP 1
\if :{?app_password}
\else
  DO $$ BEGIN
    RAISE EXCEPTION 'create-roles.sql: set the psql variable app_password';
  END $$;
\endif
\if :{?admin_password}
\else
  DO $$ BEGIN
    RAISE EXCEPTION 'create-roles.sql: set the psql variable admin_password';
  END $$;
\endif
\if :{?maintenance_password}
\else
  DO $$ BEGIN
    RAISE EXCEPTION
      'create-roles.sql: set the psql variable maintenance_password';
  END $$;
\endif

SELECT statement
  FROM (VALUES
          ('imbi_owner',
           'CREATE ROLE imbi_owner NOLOGIN'),
          ('imbi_definer',
           'CREATE ROLE imbi_definer NOLOGIN BYPASSRLS'),
          ('imbi_trigger',
           'CREATE ROLE imbi_trigger NOLOGIN BYPASSRLS'),
          ('imbi_app',
           format('CREATE ROLE imbi_app LOGIN PASSWORD %L',
                  :'app_password')),
          ('imbi_admin',
           format('CREATE ROLE imbi_admin LOGIN PASSWORD %L',
                  :'admin_password')),
          ('imbi_maintenance',
           format('CREATE ROLE imbi_maintenance LOGIN BYPASSRLS PASSWORD %L',
                  :'maintenance_password')))
       AS roles (name, statement)
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = roles.name)
\gexec

DO $$
DECLARE
  wrong text;
BEGIN
  SELECT string_agg(
           format('%s: login %s, bypassrls %s, superuser %s (expected '
                  'login %s, bypassrls %s, superuser false)',
                  e.name, r.rolcanlogin, r.rolbypassrls, r.rolsuper,
                  e.login, e.bypassrls),
           E'\n' ORDER BY e.name)
    INTO wrong
    FROM (VALUES ('imbi_owner', false, false),
                 ('imbi_definer', false, true),
                 ('imbi_trigger', false, true),
                 ('imbi_app', true, false),
                 ('imbi_admin', true, false),
                 ('imbi_maintenance', true, true))
         AS e (name, login, bypassrls)
    JOIN pg_roles AS r
      ON r.rolname = e.name
   WHERE r.rolcanlogin <> e.login
      OR r.rolbypassrls <> e.bypassrls
      OR r.rolsuper;
  IF wrong IS NOT NULL THEN
    RAISE EXCEPTION 'roles with the wrong attributes'
          USING DETAIL = wrong,
                HINT = 'Compare with schemata/README.md "Roles".';
  END IF;
END
$$;
