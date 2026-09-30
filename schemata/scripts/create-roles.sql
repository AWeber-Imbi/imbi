-- Create the six roles of README "Roles". deploy does not create roles,
-- so run this once for each cluster, before the first deploy.
--
-- The three login passwords come from psql variables:
--
--   psql -v ON_ERROR_STOP=1 \
--        -v app_password=... \
--        -v admin_password=... \
--        -v maintenance_password=... \
--        -f schemata/scripts/create-roles.sql
--
-- The script creates only the roles that do not exist, so you can run it
-- again. It does not change a role that exists.
\if :{?app_password}
\else
  \echo 'create-roles.sql: set the psql variable app_password'
  \quit 3
\endif
\if :{?admin_password}
\else
  \echo 'create-roles.sql: set the psql variable admin_password'
  \quit 3
\endif
\if :{?maintenance_password}
\else
  \echo 'create-roles.sql: set the psql variable maintenance_password'
  \quit 3
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
