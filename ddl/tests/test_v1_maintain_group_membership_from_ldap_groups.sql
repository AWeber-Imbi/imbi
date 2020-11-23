BEGIN;
SELECT plan(9);

SELECT lives_ok(
  $$INSERT INTO v1.users (username, email_address, display_name, password)
         VALUES ('test1', 'test1@imbi.local', 'Testy McTestFace', 'password')$$,
  'INSERT internal user with defaults');

SELECT is(
  v1.maintain_group_membership_from_ldap_groups(
    'test1',
    ARRAY[
      'cn=group1,cn=groups,cn=accounts,dc=imbi,dc=tld',
      'cn=group2,cn=groups,cn=accounts,dc=imbi,dc=tld',
      'cn=group3,cn=groups,cn=accounts,dc=imbi,dc=tld'
    ]
  ),
  ARRAY['group1', 'group2', 'group3'],
  'Function returns array of group names');

SELECT results_eq(
  $$SELECT "group" FROM v1.group_members WHERE username='test1'$$,
  ARRAY['group1', 'group2', 'group3'],
  'v1.group_members contain expected records');

SELECT results_eq(
  $$SELECT "name", external_id
      FROM v1.groups
     WHERE group_type='ldap'
  ORDER BY "name"$$,
  $$VALUES ('group1', 'cn=group1,cn=groups,cn=accounts,dc=imbi,dc=tld'),
           ('group2', 'cn=group2,cn=groups,cn=accounts,dc=imbi,dc=tld'),
           ('group3', 'cn=group3,cn=groups,cn=accounts,dc=imbi,dc=tld')$$,
  'v1.groups contain expected records');

SELECT lives_ok(
  $$INSERT INTO v1.groups ("name") VALUES ('group4')$$,
  'INSERT internal group with defaults');

SELECT lives_ok(
  $$INSERT INTO v1.group_members VALUES ('group4', 'test1')$$,
  'INSERT test1 INTO group4');

SELECT results_eq(
  $$SELECT "group" FROM v1.group_members WHERE username='test1'$$,
  ARRAY['group1', 'group2', 'group3', 'group4'],
  'v1.group_members contain expected records');

SELECT is(
  v1.maintain_group_membership_from_ldap_groups(
    'test1',
    ARRAY[
      'cn=group1,cn=groups,cn=accounts,dc=imbi,dc=tld',
      'cn=group2,cn=groups,cn=accounts,dc=imbi,dc=tld'
    ]
  ),
  ARRAY['group1', 'group2'],
  'Update group memberships removing group 3');

SELECT results_eq(
  $$SELECT "group" FROM v1.group_members WHERE username='test1'$$,
  ARRAY['group1', 'group2', 'group4'],
  'v1.group_members contain expected records');

SELECT * FROM finish();
ROLLBACK;
