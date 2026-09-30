-- Runbook step 4: block the AGE-era app login and end its sessions.
--
--   psql -v ON_ERROR_STOP=1 -v age_login=<AGE-era app login> \
--        -f schemata/cutover/freeze.sql
--
-- Run it as the operator (a superuser), after every app Deployment has
-- zero pods. Do not use -1: NOLOGIN must commit before the sessions are
-- ended, or an ended session can connect again before the commit. The
-- script can run again; run it again until it passes.
--
-- 1. Stops unless the AGE-era login is a separate role: it exists, it
--    is not the current user, it is not a superuser, and no other login
--    role is a member of it, directly or through another role (SET
--    ROLE works through either). If a deployment uses one role for the
--    app and the operator, create a separate operator role before the
--    cutover.
-- 2. ALTER ROLE ... NOLOGIN, so no new session can start. NOLOGIN does
--    not end a session that is already open.
-- 3. Ends the sessions of that role in every database.
-- 4. Stops when a session of that role remains, or when any other
--    client that is not a superuser is connected to this database.
SELECT set_config('cutover.age_login', :'age_login', false) AS s \gset

DO $$
DECLARE
    v_login text := current_setting('cutover.age_login');
    v_role pg_catalog.pg_roles%ROWTYPE;
    v_members text;
BEGIN
    SELECT * INTO v_role FROM pg_catalog.pg_roles WHERE rolname = v_login;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'freeze: role % does not exist', v_login;
    END IF;
    IF v_login = current_user OR v_login = session_user THEN
        RAISE EXCEPTION 'freeze: % is the operator role', v_login
              USING HINT = 'Use a separate operator role.';
    END IF;
    IF v_role.rolsuper THEN
        RAISE EXCEPTION 'freeze: % is a superuser', v_login;
    END IF;
    IF v_login IN ('imbi_owner', 'imbi_definer', 'imbi_trigger',
                   'imbi_app', 'imbi_admin', 'imbi_maintenance') THEN
        RAISE EXCEPTION 'freeze: % is a role of the relational schema',
                        v_login;
    END IF;
    -- Direct and indirect members: SET ROLE works through either.
    SELECT string_agg(m.rolname, ', ' ORDER BY m.rolname)
      INTO v_members
      FROM pg_catalog.pg_roles AS m
     WHERE m.oid <> v_role.oid
       AND m.rolcanlogin
       AND NOT m.rolsuper
       AND pg_catalog.pg_has_role(m.oid, v_role.oid, 'MEMBER');
    IF v_members IS NOT NULL THEN
        RAISE EXCEPTION 'freeze: login roles are members of %', v_login
              USING DETAIL = v_members,
                    HINT = 'NOLOGIN would not stop them.';
    END IF;
    IF NOT (SELECT rolsuper FROM pg_catalog.pg_roles
             WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'freeze: run this as a superuser';
    END IF;
END
$$;

ALTER ROLE :"age_login" NOLOGIN;

SELECT pid, datname, application_name, client_addr,
       pg_catalog.pg_terminate_backend(pid, 5000) AS terminated
  FROM pg_catalog.pg_stat_activity
 WHERE usename = :'age_login';

DO $$
DECLARE
    v_login text := current_setting('cutover.age_login');
    v_sessions text;
BEGIN
    IF (SELECT rolcanlogin FROM pg_catalog.pg_roles
         WHERE rolname = v_login) THEN
        RAISE EXCEPTION 'freeze: % can still log in', v_login;
    END IF;
    SELECT string_agg(format('%s (%s)', pid, datname), ', ')
      INTO v_sessions
      FROM pg_catalog.pg_stat_activity
     WHERE usename = v_login;
    IF v_sessions IS NOT NULL THEN
        RAISE EXCEPTION 'freeze: sessions of % remain', v_login
              USING DETAIL = v_sessions,
                    HINT = 'Run freeze.sql again.';
    END IF;
    -- No other client may be connected to this database, whatever its
    -- role: every app is stopped. Superusers are the operator and the
    -- tools of the database cluster.
    SELECT string_agg(format('%s %s (%s, %s)', a.pid, a.usename,
                             a.application_name, a.client_addr),
                      ', ')
      INTO v_sessions
      FROM pg_catalog.pg_stat_activity AS a
      JOIN pg_catalog.pg_roles AS r ON r.oid = a.usesysid
     WHERE a.datname = current_database()
       AND a.backend_type = 'client backend'
       AND a.pid <> pg_catalog.pg_backend_pid()
       AND NOT r.rolsuper;
    IF v_sessions IS NOT NULL THEN
        RAISE EXCEPTION 'freeze: other sessions are connected'
              USING DETAIL = v_sessions,
                    HINT = 'Find and stop the client, then run '
                           'freeze.sql again.';
    END IF;
    RAISE NOTICE 'freeze: % is NOLOGIN and has no session', v_login;
END
$$;
