BEGIN;
SELECT plan(11);

SELECT lives_ok(
  $$INSERT INTO v1.users (username, email_address, display_name, password)
         VALUES ('test1', 'test1@imbi.local', 'Testy McTestFace', 'password')$$,
  'INSERT internal user with defaults');

SELECT results_eq(
  $$SELECT email_address FROM v1.users WHERE username = 'test1'$$,
  $$VALUES ('test1@imbi.local')$$,
  'SELECT email_address for test1 user');

SELECT results_eq(
  $$SELECT created_at IS NOT NULL FROM v1.users WHERE username = 'test1'$$,
  $$VALUES (TRUE)$$,
  'SELECT created_at is not null for test1');

SELECT results_eq(
  $$SELECT last_seen_at IS NULL FROM v1.users WHERE username = 'test1'$$,
  $$VALUES (TRUE)$$,
  'SELECT last_seen_at is null for test1');

SELECT throws_ok(
  $$INSERT INTO v1.users (username, email_address, display_name, password)
         VALUES ('test1', 'test1@imbi.local', 'Testy McTestFace', 'password')$$,
  23505, $$duplicate key value violates unique constraint "users_pkey"$$,
  'INSERT fails with duplicate key error for users_pk');

SELECT throws_ok(
  $$INSERT INTO v1.users (username, email_address, display_name, password)
         VALUES ('test2', 'test1@imbi.local', 'Testy McTestFace', 'password')$$,
  23505, $$duplicate key value violates unique constraint "users_email_address_key"$$,
  'INSERT fails with duplicate key error for users_email_address_key');

SELECT throws_ok(
  $$INSERT INTO v1.users (username, email_address, display_name)
         VALUES ('test1', 'test1@imbi.local', 'Testy McTestFace')$$,
  23514, $$new row for relation "users" violates check constraint "nullable_password"$$,
  'INSERT fails when missing password for internal user');

SELECT throws_ok(
  $$INSERT INTO v1.users (username, email_address, display_name, external_id)
         VALUES ('test1', 'test1@imbi.local', 'Testy McTestFace', 'FAILURE')$$,
  23514, $$new row for relation "users" violates check constraint "nullable_external_id"$$,
  'INSERT fails when providing external_id for internal user');

SELECT lives_ok(
  $$INSERT INTO v1.users (username, user_type, email_address, display_name, external_id)
         VALUES ('test2', 'ldap', 'test2@imbi.local', 'Testy McTestFace 2', 'dn=test2,cn=groups,cn=accounts,dc=imbi,dc=tld')$$,
  'INSERT LDAP user with defaults');

SELECT results_eq(
  $$SELECT external_id FROM v1.users WHERE username = 'test2'$$,
  $$VALUES ('dn=test2,cn=groups,cn=accounts,dc=imbi,dc=tld')$$,
  'SELECT external_id for test2 user');

SELECT throws_ok(
  $$INSERT INTO v1.users (username, user_type, email_address, display_name, external_id)
         VALUES ('test3', 'ldap', 'test3@imbi.local', 'Testy McTestFace 2', 'dn=test2,cn=groups,cn=accounts,dc=imbi,dc=tld')$$,
  23505, $$duplicate key value violates unique constraint "users_external_id"$$,
  'INSERT fails with duplicate key error for users_external_id');

SELECT * FROM finish();
ROLLBACK;
