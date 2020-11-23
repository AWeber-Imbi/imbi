INSERT INTO v1.groups ("name", group_type, external_id, permissions)
     VALUES ('admin', 'ldap', 'cn=admin,ou=groups,dc=example,dc=org', ARRAY['admin']);
INSERT INTO v1.groups ("name", group_type, external_id, permissions)
     VALUES ('imbi', 'ldap', 'cn=imbi,ou=groups,dc=example,dc=org', ARRAY['reader']);
