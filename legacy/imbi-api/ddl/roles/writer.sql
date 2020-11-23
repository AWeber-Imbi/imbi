DO
$query$
BEGIN
  IF NOT EXISTS (SELECT * FROM pg_catalog.pg_roles WHERE rolname = 'writer')
  THEN
    CREATE ROLE writer INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOLOGIN NOREPLICATION NOBYPASSRLS;
  END IF;
END
$query$;

SET client_min_messages TO WARNING;

GRANT reader TO writer;

SET client_min_messages TO INFO;
