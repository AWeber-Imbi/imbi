import ldap3
from tornado import testing

from imbi import ldap
from tests import base

LDAP_USER = 'test'
LDAP_PASSWORD = 'password'


class ClientTestCase(base.TestCase):
    @staticmethod
    def get_user_dn(conn):
        result = conn.extend.standard.who_am_i()
        return result[3:]

    @testing.gen_test
    async def test_attributes(self):
        client = ldap.Client(self.settings['ldap'])
        conn = await client.connect(LDAP_USER, LDAP_PASSWORD)
        self.assertIsInstance(conn, ldap3.Connection)
        attributes = await client.attributes(conn, self.get_user_dn(conn))
        self.assertEqual(attributes['givenName'], 'Imbi')
        self.assertEqual(attributes['sn'], 'Test')
        self.assertEqual(attributes['mail'], 'imbi@example.org')
        conn.unbind()

    @testing.gen_test
    async def test_groups(self):
        client = ldap.Client(self.settings['ldap'])
        conn = await client.connect(LDAP_USER, LDAP_PASSWORD)
        self.assertIsInstance(conn, ldap3.Connection)
        groups = await client.groups(conn, self.get_user_dn(conn))
        self.assertIn('cn=imbi,ou=groups,dc=example,dc=org', groups)
        conn.unbind()
