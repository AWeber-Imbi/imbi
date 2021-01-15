INSERT INTO v1.groups ("name", group_type, external_id, permissions)
     VALUES ('admin', 'ldap', 'cn=admin,ou=groups,dc=example,dc=org', ARRAY['admin']);
INSERT INTO v1.groups ("name", group_type, external_id, permissions)
     VALUES ('imbi', 'ldap', 'cn=imbi,ou=groups,dc=example,dc=org', ARRAY['reader']);

INSERT INTO v1.users (username, user_type, external_id, email_address, display_name)
     VALUES ('test', 'ldap', 'cn=test,ou=users,dc=example,dc=org', 'imbi@example.org', 'Its Imbi');
INSERT INTO v1.users (username, user_type, external_id, email_address, display_name)
     VALUES ('ffink', 'ldap', 'cn=ffink,ou=users,dc=example,dc=org', 'ffink@frank-jewelry.com', 'Frank');

INSERT INTO v1.group_members("group", username) VALUES ('admin', 'test');
INSERT INTO v1.group_members("group", username) VALUES ('imbi', 'ffink');
