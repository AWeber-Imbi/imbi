DO
$query$
BEGIN
  IF NOT EXISTS (SELECT * FROM pg_catalog.pg_roles WHERE rolname = 'imbi')
  THEN
    CREATE ROLE imbi INHERIT NOCREATEROLE NOCREATEDB LOGIN PASSWORD 'imbi';
  END IF;
END
$query$;

ALTER USER imbi SET statement_timeout = 60000;  -- Maximum duration for a query
ALTER USER imbi SET idle_in_transaction_session_timeout = 60000; -- Maximum idle in transaction

SET client_min_messages TO WARNING;

GRANT reader TO imbi;
GRANT writer TO imbi;

SET client_min_messages TO INFO;
