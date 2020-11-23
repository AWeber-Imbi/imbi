BEGIN;
SELECT plan(3);

SELECT is(
  v1.group_name_from_ldap_dn('dn=Group Name,cn=groups,cn=accounts,dc=imbi,dc=tld'::TEXT),
  'Group Name'::TEXT, 'Name FROM DN variation 1 is extracted correctly');

SELECT is(
  v1.group_name_from_ldap_dn('cn=group1,cn=groups,cn=accounts,dc=imbi,dc=tld'::TEXT),
  'group1'::TEXT, 'Name FROM DN variation 2 is extracted correctly');

SELECT is(v1.group_name_from_ldap_dn(
  'DN=Group-2,cn=groups,cn=accounts,dc=imbi,dc=tld'::TEXT),
  'Group-2'::TEXT, 'Name FROM DN variation 3 is extracted correctly');

SELECT * FROM finish();
ROLLBACK;
