BEGIN;
SELECT plan(9);

SELECT lives_ok(
  $$INSERT INTO v1.groups ("name") VALUES ('test1')$$,
  'INSERT internal group with defaults');

SELECT results_eq(
  $$SELECT group_type::TEXT FROM v1.groups WHERE name = 'test1'$$,
  $$VALUES ('internal')$$,
  'SELECT internal for test1 group');

SELECT results_eq(
  $$SELECT created_at IS NOT NULL FROM v1.groups WHERE name = 'test1'$$,
  $$VALUES (TRUE)$$,
  'SELECT created_at is not null for test1');

SELECT results_eq(
  $$SELECT last_modified_at IS NULL FROM v1.groups WHERE name = 'test1'$$,
  $$VALUES (TRUE)$$,
  'SELECT modified_at is null for test1');

SELECT throws_ok(
  $$INSERT INTO v1.groups ("name") VALUES ('test1')$$,
  23505, $$duplicate key value violates unique constraint "groups_pkey"$$,
  'INSERT fails with duplicate key error for groups_pk');

SELECT throws_ok(
  $$INSERT INTO v1.groups ("name", external_id) VALUES ('test2', 'value')$$,
  23514, $$new row for relation "groups" violates check constraint "nullable_external_id"$$,
  'INSERT fails when providing external_id for internal group');

SELECT lives_ok(
  $$INSERT INTO v1.groups ("name", group_type, external_id)
         VALUES ('test2', 'ldap', 'dn=test2,cn=groups,cn=accounts,dc=imbi,dc=tld')$$,
  'INSERT LDAP group with defaults');

SELECT results_eq(
  $$SELECT external_id FROM v1.groups WHERE name = 'test2'$$,
  $$VALUES ('dn=test2,cn=groups,cn=accounts,dc=imbi,dc=tld')$$,
  'SELECT external_id for test2 group');

SELECT throws_ok(
  $$INSERT INTO v1.groups ("name", group_type, external_id)
         VALUES ('test2', 'ldap', NULL)$$,
  23514, $$new row for relation "groups" violates check constraint "nullable_external_id"$$,
  'INSERT fails when providing NULL external_id for LDAP group');

SELECT * FROM finish();
ROLLBACK;
